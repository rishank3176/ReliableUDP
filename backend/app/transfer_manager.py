"""Background UDP transfers and protocol comparison runs."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import PROTOCOLS, Settings
from .file_manager import output_paths, sanitize_filename
from .metrics import Metrics
from .models import TransferParams
from .network_simulator import NetworkSimulator
from .receiver import UdpReceiver
from .sender import perform_transfer
from .transport import TransferCancelled, TransferError

logger = logging.getLogger("reliableudp.manager")

TERMINAL = {"completed", "failed", "cancelled"}


class TransferBusy(Exception):
    """Raised when a transfer or benchmark already owns the receiver."""


@dataclass
class TransferRecord:
    id: str
    transfer_bytes: bytes
    filename: str
    created_at: str
    params: TransferParams
    output_path: Path
    metrics: Metrics = field(default_factory=Metrics)
    cancel_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class BenchmarkRun:
    id: str
    created_at: str
    filename: str
    file_size: int
    status: str
    settings: dict
    results: list[dict | None]
    error: str | None = None


class TransferManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_directories()
        self.receiver: UdpReceiver | None = None
        self._lock = threading.Lock()
        self._active: str | None = None
        self.transfers: dict[str, TransferRecord] = {}
        self._order: list[str] = []
        self.benchmarks: dict[str, BenchmarkRun] = {}
        self.latest_benchmark_id: str | None = None

    def start_receiver(self) -> None:
        if not self.settings.local_receiver:
            return
        self.receiver = UdpReceiver(
            self.settings.udp_host,
            self.settings.udp_port,
            self.settings.output_dir,
        )
        self.receiver.start_background()

    def stop_receiver(self) -> None:
        if self.receiver is not None:
            self.receiver.stop()

    def receiver_status(self) -> dict:
        receiver = self.receiver
        if not self.settings.local_receiver:
            return {"enabled": False, "running": False, "host": None, "port": None, "error": None}
        if receiver is None:
            return {
                "enabled": True,
                "running": False,
                "host": self.settings.udp_host,
                "port": self.settings.udp_port,
                "error": "Receiver has not started",
            }
        return {
            "enabled": True,
            "running": receiver.bind_error is None and receiver.bound_port is not None and not receiver._stop.is_set(),
            "host": receiver.bound_host or self.settings.udp_host,
            "port": receiver.bound_port,
            "error": receiver.bind_error,
            "invalid_packets": receiver.invalid_packets,
        }

    def create_transfer(self, upload_path: Path, filename: str, params: TransferParams) -> TransferRecord:
        record = self._new_record(filename, params)
        with self._lock:
            if self._active is not None:
                raise TransferBusy("A transfer or benchmark is already running")
            self._remember(record)
            self._active = record.id
        thread = threading.Thread(
            target=self._thread_entry,
            args=(record, upload_path),
            name=f"transfer-{record.id[:8]}",
            daemon=True,
        )
        thread.start()
        return record

    def start_benchmark(self, upload_path: Path, filename: str, params: TransferParams) -> BenchmarkRun:
        benchmark_id = uuid.uuid4().hex
        benchmark = BenchmarkRun(
            id=benchmark_id,
            created_at=_now(),
            filename=sanitize_filename(filename),
            file_size=upload_path.stat().st_size,
            status="running",
            settings=params.model_dump(),
            results=[],
        )
        with self._lock:
            if self._active is not None:
                raise TransferBusy("A transfer or benchmark is already running")
            self._active = benchmark_id
            self.benchmarks[benchmark_id] = benchmark
            self.latest_benchmark_id = benchmark_id
        thread = threading.Thread(
            target=self._benchmark_thread,
            args=(benchmark, upload_path, filename, params),
            name=f"benchmark-{benchmark_id[:8]}",
            daemon=True,
        )
        thread.start()
        return benchmark

    def get(self, transfer_id: str) -> TransferRecord | None:
        return self.transfers.get(transfer_id)

    def list_transfers(self) -> list[TransferRecord]:
        with self._lock:
            ids = list(self._order)
        return [self.transfers[item] for item in reversed(ids) if item in self.transfers]

    def cancel(self, transfer_id: str) -> TransferRecord:
        record = self.transfers.get(transfer_id)
        if record is None:
            raise KeyError(transfer_id)
        status = record.metrics.snapshot()["status"]
        if status not in TERMINAL:
            record.cancel_event.set()
            record.metrics.event("status", "Cancellation requested")
        return record

    def _thread_entry(self, record: TransferRecord, upload_path: Path) -> None:
        try:
            self._execute(record, upload_path)
        finally:
            with self._lock:
                if self._active == record.id:
                    self._active = None
            _remove(upload_path)

    def _benchmark_thread(
        self,
        benchmark: BenchmarkRun,
        upload_path: Path,
        filename: str,
        params: TransferParams,
    ) -> None:
        try:
            for protocol in PROTOCOLS:
                protocol_params = params.model_copy(update={"protocol": protocol})
                record = self._new_record(filename, protocol_params)
                with self._lock:
                    self._remember(record)
                self._execute(record, upload_path)
                benchmark.results.append(_result_row(record))
            benchmark.status = "completed"
        except Exception as exc:
            logger.exception("Benchmark failed")
            benchmark.status = "failed"
            benchmark.error = "The comparison could not be completed"
            if isinstance(exc, (TransferError, TransferBusy)):
                benchmark.error = str(exc)
        finally:
            with self._lock:
                if self._active == benchmark.id:
                    self._active = None
            _remove(upload_path)

    def _execute(self, record: TransferRecord, upload_path: Path) -> None:
        receiver_simulator = None
        try:
            if self._targets_local(record.params):
                seed = None if record.params.seed is None else record.params.seed + 1
                receiver_simulator = NetworkSimulator.from_percents(
                    record.params.loss_percent,
                    record.params.corruption_percent,
                    record.params.delay_ms,
                    seed,
                )
                if self.receiver is not None:
                    self.receiver.set_simulator(receiver_simulator)
            elif self._missing_local_receiver(record.params):
                raise TransferError(
                    "The built-in UDP receiver is not running. Start the backend, or point the "
                    "transfer at a standalone receiver."
                )
            perform_transfer(
                upload_path,
                record.params,
                record.metrics,
                record.cancel_event,
                transfer_id=record.transfer_bytes,
                receiver_simulator=receiver_simulator,
                original_name=record.filename,
            )
        except TransferCancelled:
            record.metrics.mark_cancelled()
        except TransferError as exc:
            record.metrics.mark_failed(str(exc))
        except Exception:
            logger.exception("Transfer %s failed", record.id)
            record.metrics.mark_failed("Unexpected transfer error")
        else:
            record.metrics.mark_completed()

    def _new_record(self, filename: str, params: TransferParams) -> TransferRecord:
        transfer_bytes = uuid.uuid4().bytes
        transfer_hex = transfer_bytes.hex()
        safe = sanitize_filename(filename)
        _partial, final = output_paths(self.settings.output_dir, transfer_hex, safe)
        return TransferRecord(
            id=transfer_hex,
            transfer_bytes=transfer_bytes,
            filename=safe,
            created_at=_now(),
            params=params,
            output_path=final,
        )

    def _remember(self, record: TransferRecord) -> None:
        self.transfers[record.id] = record
        self._order.append(record.id)
        if len(self._order) > 100:
            forgotten = self._order.pop(0)
            self.transfers.pop(forgotten, None)

    def _targets_local(self, params: TransferParams) -> bool:
        receiver = self.receiver
        if receiver is None or receiver.bind_error or receiver.bound_port is None:
            return False
        if params.receiver_port != receiver.bound_port:
            return False
        host = params.receiver_host.lower().strip(".")
        bound = (self.settings.udp_host or "").lower()
        loopback = {"127.0.0.1", "localhost", "::1"}
        if host in loopback and bound in loopback | {"0.0.0.0", "::"}:
            return True
        return host == bound

    def _missing_local_receiver(self, params: TransferParams) -> bool:
        if not self.settings.local_receiver:
            return False
        host = params.receiver_host.lower().strip(".")
        loopback = {"127.0.0.1", "localhost", "::1"}
        bound = (self.settings.udp_host or "").lower()
        if host not in loopback and host != bound:
            return False
        receiver = self.receiver
        if receiver is not None and receiver.bound_port and receiver.bind_error is None:
            return False
        return params.receiver_port == self.settings.udp_port


def public_transfer(record: TransferRecord) -> dict:
    snapshot = record.metrics.snapshot()
    available = (
        snapshot["status"] == "completed"
        and snapshot["integrity"] == "verified"
        and record.output_path.is_file()
    )
    return {
        "id": record.id,
        "filename": record.filename,
        "created_at": record.created_at,
        "download_available": available,
        **snapshot,
    }


def public_benchmark(benchmark: BenchmarkRun) -> dict:
    return {
        "id": benchmark.id,
        "created_at": benchmark.created_at,
        "filename": benchmark.filename,
        "file_size": benchmark.file_size,
        "status": benchmark.status,
        "settings": benchmark.settings,
        "results": list(benchmark.results),
        "error": benchmark.error,
    }


def _result_row(record: TransferRecord) -> dict:
    view = public_transfer(record)
    return {
        "transfer_id": view["id"],
        "protocol": view["protocol"],
        "status": view["status"],
        "integrity": view["integrity"],
        "error": view["error"],
        "file_size": view["file_size"],
        "duration_seconds": view["duration_seconds"],
        "average_throughput_bps": view["average_throughput_bps"],
        "average_rtt_ms": view["average_rtt_ms"],
        "min_rtt_ms": view["min_rtt_ms"],
        "max_rtt_ms": view["max_rtt_ms"],
        "retransmissions": view["retransmissions"],
        "transmission_attempts": view["transmission_attempts"],
        "packets_dropped": view["simulator"]["dropped"],
        "packets_corrupted": view["simulator"]["corrupted"],
        "window_size": view["window_size"],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temporary upload")
