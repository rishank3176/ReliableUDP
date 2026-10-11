"""Shared UDP transfer harness for protocol tests."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.file_manager import output_paths, sanitize_filename
from app.metrics import Metrics
from app.models import TransferParams
from app.network_simulator import NetworkSimulator
from app.receiver import UdpReceiver
from app.sender import perform_transfer
from app.transport import TransferCancelled


def run_transfer(
    tmp_path: Path,
    payload: bytes,
    protocol: str,
    *,
    window_size: int = 4,
    chunk_size: int = 128,
    ack_timeout_ms: int = 400,
    max_retries: int = 6,
    loss_percent: float = 0,
    delay_ms: float = 0,
    corruption_percent: float = 0,
    seed: int | None = None,
    sender_simulator: NetworkSimulator | None = None,
    receiver_simulator: NetworkSimulator | None = None,
    filename: str = "payload.bin",
) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    output = tmp_path / "received"
    receiver = UdpReceiver("127.0.0.1", 0, output, receiver_simulator)
    receiver.start_background()
    if receiver.bind_error:
        raise RuntimeError(receiver.bind_error)
    params = TransferParams(
        protocol=protocol,
        window_size=window_size,
        chunk_size=chunk_size,
        ack_timeout_ms=ack_timeout_ms,
        max_retries=max_retries,
        receiver_host="127.0.0.1",
        receiver_port=receiver.bound_port,
        loss_percent=loss_percent,
        delay_ms=delay_ms,
        corruption_percent=corruption_percent,
        seed=seed,
    )
    if receiver_simulator is None and (loss_percent or delay_ms or corruption_percent):
        receiver_simulator = NetworkSimulator.from_percents(
            loss_percent,
            corruption_percent,
            delay_ms,
            None if seed is None else seed + 1,
        )
        receiver.set_simulator(receiver_simulator)
    metrics = Metrics()
    transfer_id = uuid.uuid4().bytes
    try:
        perform_transfer(
            source,
            params,
            metrics,
            transfer_id=transfer_id,
            simulator=sender_simulator,
            receiver_simulator=receiver_simulator,
            original_name=filename,
        )
    except TransferCancelled:
        metrics.mark_cancelled()
    except Exception as exc:
        metrics.mark_failed(str(exc))
    else:
        metrics.mark_completed()
    finally:
        receiver.stop()
    safe = sanitize_filename(filename)
    _partial, final = output_paths(output, transfer_id.hex(), safe)
    return {
        "snapshot": metrics.snapshot(),
        "metrics": metrics,
        "output": final,
        "receiver": receiver,
        "transfer_id": transfer_id.hex(),
    }
