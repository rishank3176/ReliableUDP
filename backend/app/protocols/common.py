"""Handshake, completion, and DATA transmission shared by the protocols."""

from __future__ import annotations

import json
import threading
import time

from ..file_manager import ChunkSource, FileMetadata
from ..metrics import Metrics
from ..packet import FLAG_RETRANSMIT, Packet, PacketType
from ..transport import Peer, TransferError, raise_if_cancelled


def control_packet(
    packet_type: PacketType,
    transfer_id: bytes,
    body: dict | None = None,
    seq: int = 0,
    ack: int = 0,
) -> Packet:
    payload = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    return Packet(
        packet_type=packet_type,
        transfer_id=transfer_id,
        seq=seq,
        ack=ack,
        payload=payload,
    )


def transmit_data(
    peer: Peer,
    metrics: Metrics,
    source: ChunkSource,
    transfer_id: bytes,
    seq: int,
    retransmit: bool,
) -> None:
    payload = source.get(seq)
    started = time.monotonic()
    packet = Packet(
        packet_type=PacketType.DATA,
        transfer_id=transfer_id,
        seq=seq,
        flags=FLAG_RETRANSMIT if retransmit else 0,
        payload=payload,
    )
    peer.send(packet, retransmit=retransmit)
    completed = time.monotonic()
    metrics.note_data_send(seq, len(payload), retransmit, started, completed)


def handshake(
    peer: Peer,
    meta: FileMetadata,
    metrics: Metrics,
    cancel_event: threading.Event | None,
    timeout: float,
    max_retries: int,
) -> None:
    packet = control_packet(PacketType.START, peer.transfer_id, meta.to_dict())
    metrics.event("handshake", "Sending START")
    for attempt in range(max_retries + 1):
        raise_if_cancelled(cancel_event)
        metrics.note_control(retransmit=attempt > 0)
        peer.send(packet, retransmit=attempt > 0)
        response = peer.recv_matching(
            timeout,
            lambda incoming: incoming.packet_type == PacketType.READY,
        )
        if response is not None:
            metrics.event("handshake", "Receiver is ready")
            return
    raise TransferError(
        "Receiver did not become ready. Check the receiver address, UDP port, and firewall."
    )


def finish(
    peer: Peer,
    meta: FileMetadata,
    metrics: Metrics,
    cancel_event: threading.Event | None,
    timeout: float,
    max_retries: int,
) -> None:
    metrics.set_status("verifying")
    packet = control_packet(
        PacketType.FIN,
        peer.transfer_id,
        {"total_chunks": meta.total_chunks, "sha256": meta.sha256},
    )
    metrics.event("fin", "Sending FIN and waiting for integrity confirmation")
    last_problem = "Receiver did not confirm file reconstruction"
    for attempt in range(max_retries + 1):
        raise_if_cancelled(cancel_event)
        metrics.note_control(retransmit=attempt > 0)
        peer.send(packet, retransmit=attempt > 0)
        response = peer.recv_matching(
            timeout,
            lambda incoming: incoming.packet_type == PacketType.FIN_ACK,
        )
        if response is None:
            continue
        try:
            body = json.loads(response.payload.decode("utf-8")) if response.payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransferError("Receiver sent an unreadable completion message") from exc
        digest = body.get("sha256")
        if body.get("ok") is True:
            if digest != meta.sha256:
                metrics.mark_mismatch(str(digest) if digest else None, "Receiver digest does not match")
                raise TransferError("Receiver confirmation did not match the original SHA256")
            metrics.mark_verified(meta.sha256)
            return
        message = str(body.get("message") or "Receiver rejected the reconstructed file")
        metrics.mark_mismatch(str(digest) if digest else None, message)
        raise TransferError(message)
    raise TransferError(last_problem)
