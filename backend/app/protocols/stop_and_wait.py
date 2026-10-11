"""Stop-and-Wait sender and receiver.

The sender transmits one DATA packet and waits for a cumulative ACK whose
acknowledgement number is the next sequence number. The effective window is
always 1. The receiver accepts only the next in-order packet.
"""

from __future__ import annotations

import threading

from ..file_manager import ChunkSource, FileMetadata, FileReassembler, expected_chunk_length
from ..metrics import Metrics
from ..packet import Packet, PacketType
from ..transport import Peer, TransferError, raise_if_cancelled
from .common import control_packet, finish, handshake, transmit_data


def run_stop_and_wait(
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
    for seq in range(meta.total_chunks):
        retransmits = 0
        while True:
            raise_if_cancelled(cancel_event)
            transmit_data(peer, metrics, source, peer.transfer_id, seq, retransmit=retransmits > 0)
            ack = peer.recv_matching(
                timeout,
                lambda packet, expected=seq + 1: (
                    packet.packet_type == PacketType.ACK and packet.ack == expected
                ),
            )
            if ack is not None:
                metrics.note_ack_sequences([seq])
                metrics.event("ack", f"Stop-and-Wait ACK {ack.ack}")
                break
            retransmits += 1
            metrics.event("timeout", f"Timeout waiting for ACK of packet {seq}")
            if retransmits > max_retries:
                raise TransferError(f"Retry limit exceeded for packet {seq}")
    finish(peer, meta, metrics, cancel_event, timeout, max_retries)


class StopAndWaitReceiver:
    """Accepts DATA only when its sequence equals the next expected number."""

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
                self.writer.write_chunk(seq, packet.payload)
                self.expected += 1
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
