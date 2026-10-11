"""Selective Repeat sender and receiver.

The sender tracks acknowledgement of each sequence number and retransmits only
packets whose own timer has expired. The receiver accepts any valid DATA packet
inside its receive window, writes it at ``sequence * chunk_size``, and returns
a SACK for that sequence. The receive window advances when the next contiguous
sequence is present.
"""

from __future__ import annotations

import threading
import time

from ..file_manager import ChunkSource, FileMetadata, FileReassembler, expected_chunk_length
from ..metrics import Metrics
from ..packet import Packet, PacketType
from ..transport import Peer, TransferError, raise_if_cancelled
from .common import control_packet, finish, handshake, transmit_data


def run_selective_repeat(
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
    acked: set[int] = set()
    retries: dict[int, int] = {}
    window = meta.window_size

    def slide() -> int:
        nonlocal base
        while base in acked and base < meta.total_chunks:
            base += 1
        return base

    while base < meta.total_chunks:
        raise_if_cancelled(cancel_event)
        while next_seq < meta.total_chunks and next_seq < base + window:
            transmit_data(peer, metrics, source, peer.transfer_id, next_seq, retransmit=False)
            retries.setdefault(next_seq, 0)
            next_seq += 1

        if _absorb_sacks(peer, metrics, base, next_seq, acked, block_for=0.0):
            slide()
        outstanding = [seq for seq in range(base, next_seq) if seq not in acked]
        if not outstanding:
            continue

        now = time.monotonic()
        waits = []
        for seq in outstanding:
            anchor = metrics.timer_anchor_for(seq)
            waits.append(0.0 if anchor is None else timeout - (now - anchor))
        remaining = max(0.0, min(waits) if waits else 0.0)
        if remaining > 0 and _absorb_sacks(peer, metrics, base, next_seq, acked, block_for=remaining):
            slide()
            outstanding = [seq for seq in range(base, next_seq) if seq not in acked]
        if not outstanding:
            continue
        sent = _retransmit_expired(
            peer, source, metrics, base, next_seq, acked, retries, timeout, max_retries
        )
        slide()
        if sent == 0 and remaining <= 0:
            time.sleep(0.005)
    finish(peer, meta, metrics, cancel_event, timeout, max_retries)


def _absorb_sacks(
    peer: Peer,
    metrics: Metrics,
    base: int,
    next_seq: int,
    acked: set[int],
    block_for: float,
) -> bool:
    """Record selective acknowledgements. Returns True when a new one arrives."""
    progressed = False
    wait = block_for
    while True:
        def relevant(packet: Packet, low: int = base, high: int = next_seq) -> bool:
            return packet.packet_type == PacketType.SACK and low <= packet.ack < high

        sack = peer.recv_matching(wait, relevant)
        wait = 0.0
        if sack is None:
            return progressed
        if sack.ack in acked:
            metrics.note_duplicate_ack()
            continue
        acked.add(sack.ack)
        metrics.note_ack_sequences([sack.ack])
        metrics.event("sack", f"Selective ACK for packet {sack.ack}")
        progressed = True


def _retransmit_expired(
    peer: Peer,
    source: ChunkSource,
    metrics: Metrics,
    base: int,
    next_seq: int,
    acked: set[int],
    retries: dict[int, int],
    timeout: float,
    max_retries: int,
) -> int:
    now = time.monotonic()
    sent = 0
    for seq in range(base, next_seq):
        if seq in acked:
            continue
        anchor = metrics.timer_anchor_for(seq)
        if anchor is None or now - anchor < timeout:
            continue
        if retries.get(seq, 0) >= max_retries:
            raise TransferError(f"Retry limit exceeded for packet {seq}")
        metrics.event("timeout", f"Selective Repeat timeout for packet {seq}")
        transmit_data(peer, metrics, source, peer.transfer_id, seq, retransmit=True)
        retries[seq] = retries.get(seq, 0) + 1
        sent += 1
    return sent


class SelectiveRepeatReceiver:
    """Buffers in-window packets and advances across the contiguous prefix."""

    def __init__(self, meta: FileMetadata, writer: FileReassembler, send_fn, transfer_id: bytes) -> None:
        self.meta = meta
        self.writer = writer
        self.send_fn = send_fn
        self.transfer_id = transfer_id
        self.recv_base = 0
        self.window = meta.window_size
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
        if seq < self.recv_base:
            self._sack(seq, addr)
            return
        if seq >= self.recv_base + self.window or seq >= self.meta.total_chunks:
            return
        expected_len = expected_chunk_length(
            self.meta.file_size, self.meta.chunk_size, seq, self.meta.total_chunks
        )
        if len(packet.payload) != expected_len:
            return
        self.writer.write_chunk(seq, packet.payload)
        self._sack(seq, addr)
        while self.recv_base in self.writer.received:
            self.recv_base += 1

    def _sack(self, seq: int, addr) -> None:
        self.send_fn(
            control_packet(PacketType.SACK, self.transfer_id, ack=seq),
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
