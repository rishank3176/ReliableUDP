"""UDP sender orchestration and a small command-line sender."""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import uuid
from pathlib import Path

from .config import PROTOCOL_LABELS, PROTOCOL_STOP_AND_WAIT
from .file_manager import ChunkSource, FileMetadata, sanitize_filename, sha256_file, total_chunks_for
from .metrics import Metrics
from .models import TransferParams
from .network_simulator import NetworkSimulator
from .protocols.go_back_n import run_go_back_n
from .protocols.selective_repeat import run_selective_repeat
from .protocols.stop_and_wait import run_stop_and_wait
from .transport import Peer, TransferCancelled, TransferError, bind_udp

logger = logging.getLogger("reliableudp.sender")

_RUNNERS = {
    "stop_and_wait": run_stop_and_wait,
    "go_back_n": run_go_back_n,
    "selective_repeat": run_selective_repeat,
}


def perform_transfer(
    file_path: Path,
    params: TransferParams,
    metrics: Metrics,
    cancel_event: threading.Event | None = None,
    transfer_id: bytes | None = None,
    simulator: NetworkSimulator | None = None,
    receiver_simulator: NetworkSimulator | None = None,
    original_name: str | None = None,
) -> None:
    """Send ``file_path`` to the configured receiver over UDP.

    Raises TransferError or TransferCancelled. The caller records the final status.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        raise TransferError("The file to send does not exist")
    file_size = file_path.stat().st_size
    digest = sha256_file(file_path)
    protocol = params.protocol
    window = 1 if protocol == PROTOCOL_STOP_AND_WAIT else params.window_size
    total_chunks = total_chunks_for(file_size, params.chunk_size)
    meta = FileMetadata.from_dict(
        {
            "filename": sanitize_filename(original_name or file_path.name),
            "file_size": file_size,
            "chunk_size": params.chunk_size,
            "total_chunks": total_chunks,
            "protocol": protocol,
            "window_size": window,
            "sha256": digest,
        }
    )
    transfer_id = transfer_id or uuid.uuid4().bytes
    metrics.configure(
        file_size=file_size,
        total_chunks=total_chunks,
        protocol=protocol,
        window_size=window,
        chunk_size=params.chunk_size,
        ack_timeout_ms=params.ack_timeout_ms,
        max_retries=params.max_retries,
        loss_percent=params.loss_percent,
        delay_ms=params.delay_ms,
        corruption_percent=params.corruption_percent,
        expected_sha256=digest,
    )
    if metrics.started_monotonic is None:
        metrics.mark_started()
    if simulator is None:
        seed = params.seed
        simulator = NetworkSimulator.from_percents(
            params.loss_percent,
            params.corruption_percent,
            params.delay_ms,
            seed,
        )
    metrics.attach_simulators(simulator, receiver_simulator)
    source = ChunkSource(file_path, params.chunk_size, file_size)
    sock = bind_udp("0.0.0.0", 0)
    try:
        peer = Peer(
            sock,
            (params.receiver_host, params.receiver_port),
            transfer_id,
            simulator,
            cancel_event,
            metrics,
        )
        logger.info(
            "Sending %s bytes with %s to %s:%s",
            file_size,
            PROTOCOL_LABELS.get(protocol, protocol),
            params.receiver_host,
            params.receiver_port,
        )
        _RUNNERS[protocol](
            peer,
            source,
            meta,
            metrics,
            cancel_event,
            params.ack_timeout_ms / 1000.0,
            params.max_retries,
        )
    except (OSError, socket.gaierror) as exc:
        raise TransferError(f"UDP socket error: {exc.strerror or exc}") from exc
    finally:
        source.close()
        try:
            sock.close()
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ReliableUDP standalone sender")
    parser.add_argument("--file", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--protocol", default="go_back_n", choices=list(_RUNNERS))
    parser.add_argument("--window", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=1024)
    parser.add_argument("--timeout-ms", type=int, default=500)
    parser.add_argument("--retries", type=int, default=8)
    parser.add_argument("--loss", type=float, default=0.0)
    parser.add_argument("--corruption", type=float, default=0.0)
    parser.add_argument("--delay-ms", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    params = TransferParams(
        protocol=args.protocol,
        window_size=args.window,
        chunk_size=args.chunk_size,
        ack_timeout_ms=args.timeout_ms,
        max_retries=args.retries,
        receiver_host=args.host,
        receiver_port=args.port,
        loss_percent=args.loss,
        delay_ms=args.delay_ms,
        corruption_percent=args.corruption,
        seed=args.seed,
    )
    metrics = Metrics()
    try:
        perform_transfer(Path(args.file), params, metrics)
    except TransferCancelled:
        metrics.mark_cancelled()
    except Exception as exc:
        logging.getLogger("reliableudp.sender").error("%s", exc)
        metrics.mark_failed(str(exc))
    else:
        metrics.mark_completed()
    snapshot = metrics.snapshot()
    print(f"status: {snapshot['status']}")
    print(f"integrity: {snapshot['integrity']}")
    print(f"duration_seconds: {snapshot['duration_seconds']}")
    print(f"average_throughput_bps: {snapshot['average_throughput_bps']}")
    print(f"retransmissions: {snapshot['retransmissions']}")
    print(f"sha256: {snapshot['received_sha256']}")
    if snapshot["error"]:
        print(f"error: {snapshot['error']}")
    return 0 if snapshot["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
