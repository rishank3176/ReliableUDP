"""Go-Back-N sender and receiver.

The sender keeps a sliding window of outstanding DATA packets. Acknowledgements
are cumulative. When the timer for the oldest unacknowledged packet expires,
every outstanding packet in the window is retransmitted.

The receiver accepts a DATA packet only when it is the next expected sequence
number. Out-of-order packets are discarded. Every response carries the next
expected sequence number.
"""

from __future__ import annotations

import threading
import time

from ..file_manager import ChunkSource, FileMetadata, FileReassembler, expected_chunk_length
from ..metrics import Metrics
from ..packet import Packet, PacketType
from ..transport import Peer, TransferError, raise_if_cancelled
from .common import control_packet, finish, handshake, transmit_data


def run_go_back_n(
    peer: Peer,
    source: ChunkSource,
    meta: FileMetadata,
    metrics: Metrics,
    cancel_event: threading.Event | None,
    timeout: float,
    max_retries: int,
) -> None:
    handshake(peer, meta, metrics, cancel_event, timeout, max_retries)
    if meta.total_chunks == 0:
        finish(peer, meta, metrics, cancel_event, timeout, max_retries)
        return
    metrics.set_status("transferring")
    base = 0
    next_seq = 0
    stalls = 0
    window = meta.window_size
    while base < meta.total_chunks:
        raise_if_cancelled(cancel_event)
        while next_seq < meta.total_chunks and next_seq < base + window:
            transmit_data(peer, metrics, source, peer.transfer_id, next_seq, retransmit=False)
            next_seq += 1

        advanced = _consume_cumulative(peer, metrics, base, next_seq, block_for=0.0)
        if advanced > base:
            base = advanced
            stalls = 0
            continue

        anchor = metrics.timer_anchor_for(base)
        remaining = 0.0 if anchor is None else timeout - (time.monotonic() - anchor)
        if remaining > 0:
            advanced = _consume_cumulative(peer, metrics, base, next_seq, block_for=remaining)
            if advanced > base:
                base = advanced
                stalls = 0
                continue
        stalls += 1
        if stalls > max_retries:
            raise TransferError(f"Retry limit exceeded at sequence {base}")
        metrics.event(
            "timeout",
            f"Go-Back-N timeout; retransmitting packets {base} through {next_seq - 1}",
        )
        for seq in range(base, next_seq):
            transmit_data(peer, metrics, source, peer.transfer_id, seq, retransmit=True)
    finish(peer, meta, metrics, cancel_event, timeout, max_retries)


def _consume_cumulative(peer: Peer, metrics: Metrics, base: int, next_seq: int, block_for: float) -> int:
    """Apply cumulative ACKs. A positive wait ends early only when the base advances."""
    current = base
    deadline = time.monotonic() + max(block_for, 0.0)
    drain_only = block_for <= 0
    while current < next_seq:
        if drain_only:
            wait = 0.0
        else:
            wait = deadline - time.monotonic()
            if wait <= 0:
                break

        def relevant(packet: Packet, lowest: int = current, highest: int = next_seq) -> bool:
            return packet.packet_type == PacketType.ACK and lowest <= packet.ack <= highest

        ack = peer.recv_matching(wait, relevant)
        if ack is None:
            break
        if ack.ack > current:
            metrics.note_ack_sequences(range(current, ack.ack))
            metrics.event("ack", f"Cumulative ACK advances base to {ack.ack}")
            current = ack.ack
            drain_only = True
        else:
            metrics.note_duplicate_ack()
    return current


class GoBackNReceiver:
    """In-order receiver. Out-of-order DATA is discarded and the cumulative ACK is repeated."""

    def __init__(self, meta: FileMetadata, writer: FileReassembler, send_fn, transfer_id: bytes) -> None:
        self.meta = meta
        self.writer = writer
        self.send_fn = send_fn
        self.transfer_id = transfer_id
        self.expected = 0
        self.final_response: Packet | None = None
        self.output_path = None

    def handle(self, packet: Packet, addr) -> None:
        if packet.packet_type == PacketType.START:
            self.send_fn(control_packet(PacketType.READY, self.transfer_id, {"ok": True}), addr, False)
            return
        if packet.packet_type == PacketType.FIN:
            self._handle_fin(addr)
            return
        if packet.packet_type != PacketType.DATA:
            return
        seq = packet.seq
        if seq == self.expected and self.expected < self.meta.total_chunks:
            expected_len = expected_chunk_length(
                self.meta.file_size, self.meta.chunk_size, seq, self.meta.total_chunks
            )
            if len(packet.payload) == expected_len:
                if self.writer.write_chunk(seq, packet.payload):
                    self.expected += 1
        elif seq != self.expected:
            # Duplicate or out-of-order data is not written.
            pass
        self.send_fn(
            control_packet(PacketType.ACK, self.transfer_id, ack=self.expected),
            addr,
            False,
        )

    def _handle_fin(self, addr) -> None:
        if self.final_response is not None:
            self.send_fn(self.final_response, addr, True)
            return
        if not self.writer.complete():
            body = {"ok": False, "message": "File is incomplete", "sha256": None}
            self.final_response = control_packet(PacketType.FIN_ACK, self.transfer_id, body)
            self.writer.abort()
            self.send_fn(self.final_response, addr, False)
            return
        ok, digest, _size = self.writer.verify()
        if ok:
            self.output_path = str(self.writer.finalize(digest))
            body = {"ok": True, "sha256": digest, "file_size": self.meta.file_size, "message": "verified"}
        else:
            body = {"ok": False, "sha256": digest, "message": "SHA256 mismatch or size mismatch"}
            self.writer.abort()
        self.final_response = control_packet(PacketType.FIN_ACK, self.transfer_id, body)
        self.send_fn(self.final_response, addr, False)
