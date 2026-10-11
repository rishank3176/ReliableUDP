"""Thread-safe transfer metrics.

Definitions used by the API and dashboard:

- Duration is monotonic time from transfer start through completion or failure.
- Throughput is acknowledged original file payload bytes divided by duration.
  Retransmitted bytes are not counted as additional file data.
- A current throughput sample uses acknowledged bytes over the most recent
  one-second sample window when that window exists.
- An RTT sample is the time from the start of a data transmission (before
  sender-side simulated delay) until the acknowledgement that accepts it.
  Samples are recorded only for packets that were not retransmitted, so a late
  acknowledgement cannot be paired with the wrong transmission.
- Retransmissions are extra DATA transmissions after the first send of a
  sequence number.
- Simulator drop rate is dropped datagrams divided by datagrams submitted to
  the simulator. Data drops are reported separately by category.
"""

from __future__ import annotations

import threading
import time
from typing import Iterable

from .events import EventLog
from .network_simulator import NetworkSimulator


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.events = EventLog()
        self.status = "queued"
        self.error: str | None = None
        self.integrity = "pending"
        self.started_monotonic: float | None = None
        self.finished_monotonic: float | None = None
        self.file_size = 0
        self.total_chunks = 0
        self.protocol = ""
        self.window_size = 1
        self.chunk_size = 0
        self.ack_timeout_ms = 0
        self.max_retries = 0
        self.loss_percent = 0.0
        self.delay_ms = 0.0
        self.corruption_percent = 0.0
        self.bytes_acked = 0
        self.packets_acked = 0
        self.data_transmissions = 0
        self.retransmissions = 0
        self.control_transmissions = 0
        self.control_retries = 0
        self.duplicate_acks = 0
        self.invalid_packets = 0
        self.expected_sha256 = ""
        self.received_sha256: str | None = None
        self.chunk_lengths: dict[int, int] = {}
        self.rtt_anchor: dict[int, float] = {}
        self.timer_anchor: dict[int, float] = {}
        self.ever_retransmitted: set[int] = set()
        self.acked: set[int] = set()
        self.retransmitted_sequences: list[int] = []
        self.rtt_count = 0
        self.rtt_sum = 0.0
        self.rtt_min: float | None = None
        self.rtt_max: float | None = None
        self.samples: list[dict] = []
        self.sender_simulator: NetworkSimulator | None = None
        self.receiver_simulator: NetworkSimulator | None = None
        self._last_sample_at = 0.0

    def configure(
        self,
        *,
        file_size: int,
        total_chunks: int,
        protocol: str,
        window_size: int,
        chunk_size: int,
        ack_timeout_ms: int,
        max_retries: int,
        loss_percent: float,
        delay_ms: float,
        corruption_percent: float,
        expected_sha256: str,
    ) -> None:
        with self._lock:
            self.file_size = file_size
            self.total_chunks = total_chunks
            self.protocol = protocol
            self.window_size = window_size
            self.chunk_size = chunk_size
            self.ack_timeout_ms = ack_timeout_ms
            self.max_retries = max_retries
            self.loss_percent = loss_percent
            self.delay_ms = delay_ms
            self.corruption_percent = corruption_percent
            self.expected_sha256 = expected_sha256

    def attach_simulators(
        self,
        sender: NetworkSimulator | None,
        receiver: NetworkSimulator | None,
    ) -> None:
        with self._lock:
            self.sender_simulator = sender
            self.receiver_simulator = receiver

    def mark_started(self) -> None:
        with self._lock:
            self.started_monotonic = time.monotonic()
            self.status = "initializing"
        self.events.add("status", "Transfer started")

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status
        self.events.add("status", status)

    def event(self, kind: str, message: str, **fields) -> None:
        self.events.add(kind, message, **fields)

    def note_control(self, retransmit: bool) -> None:
        with self._lock:
            self.control_transmissions += 1
            if retransmit:
                self.control_retries += 1

    def note_data_send(
        self,
        seq: int,
        length: int,
        retransmit: bool,
        rtt_anchor: float,
        timer_anchor: float,
    ) -> None:
        with self._lock:
            self.chunk_lengths[seq] = length
            self.rtt_anchor[seq] = rtt_anchor
            self.timer_anchor[seq] = timer_anchor
            self.data_transmissions += 1
            if retransmit:
                self.retransmissions += 1
                self.ever_retransmitted.add(seq)
                self.retransmitted_sequences.append(seq)
        if retransmit:
            self.events.add("retransmit", f"Retransmitted data packet {seq}", seq=seq)
        else:
            self.events.add("send", f"Sent data packet {seq}", seq=seq)

    def note_ack_sequences(self, sequences: Iterable[int], now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        newly = 0
        with self._lock:
            for seq in sequences:
                if seq in self.acked:
                    continue
                self.acked.add(seq)
                self.packets_acked += 1
                self.bytes_acked += self.chunk_lengths.get(seq, 0)
                newly += 1
                if seq not in self.ever_retransmitted and seq in self.rtt_anchor:
                    self._add_rtt(moment - self.rtt_anchor[seq])
            if newly:
                self._sample_progress(moment)
        if newly:
            self.events.add("ack", f"Acknowledged {newly} data packet(s)")

    def note_duplicate_ack(self) -> None:
        with self._lock:
            self.duplicate_acks += 1

    def note_invalid(self) -> None:
        with self._lock:
            self.invalid_packets += 1

    def mark_verified(self, digest: str) -> None:
        with self._lock:
            self.integrity = "verified"
            self.received_sha256 = digest
            self._sample_progress(time.monotonic())
        self.events.add("integrity", "SHA256 verified")

    def mark_mismatch(self, digest: str | None, message: str) -> None:
        with self._lock:
            self.integrity = "mismatch"
            self.received_sha256 = digest
        self.events.add("integrity", message)

    def mark_completed(self) -> None:
        with self._lock:
            if self.integrity != "verified":
                self.status = "failed"
                self.error = "Transfer ended without integrity verification"
                self.finished_monotonic = time.monotonic()
                return
            self.status = "completed"
            self.error = None
            self.finished_monotonic = time.monotonic()
            self._sample_progress(self.finished_monotonic)
        self.events.add("status", "Transfer completed")

    def mark_failed(self, message: str) -> None:
        with self._lock:
            if self.status in {"completed", "cancelled"}:
                return
            self.status = "failed"
            self.error = message
            self.finished_monotonic = time.monotonic()
            if self.integrity == "pending":
                self.integrity = "not_checked"
        self.events.add("status", message)

    def mark_cancelled(self) -> None:
        with self._lock:
            if self.status == "completed":
                return
            self.status = "cancelled"
            self.error = "Transfer cancelled"
            self.finished_monotonic = time.monotonic()
            if self.integrity == "pending":
                self.integrity = "not_checked"
        self.events.add("status", "Transfer cancelled")

    def timer_anchor_for(self, seq: int) -> float | None:
        with self._lock:
            return self.timer_anchor.get(seq)

    def _add_rtt(self, sample: float) -> None:
        self.rtt_count += 1
        self.rtt_sum += sample
        self.rtt_min = sample if self.rtt_min is None else min(self.rtt_min, sample)
        self.rtt_max = sample if self.rtt_max is None else max(self.rtt_max, sample)

    def _progress_unlocked(self) -> float:
        if self.file_size == 0:
            if self.status in {"verifying", "completed"} or self.integrity == "verified":
                return 100.0
            return 0.0
        return min(100.0, (self.bytes_acked / self.file_size) * 100.0)

    def _sample_progress(self, now: float) -> None:
        if self.started_monotonic is None:
            return
        elapsed = now - self.started_monotonic
        point = {
            "t": round(elapsed, 3),
            "bytes": self.bytes_acked,
            "progress": round(self._progress_unlocked(), 2),
        }
        if self.samples and elapsed - self.samples[-1]["t"] < 0.05:
            if len(self.samples) == 1 and point["bytes"] != self.samples[0]["bytes"]:
                self.samples.append(point)
            else:
                self.samples[-1] = point
            return
        self.samples.append(point)
        if len(self.samples) > 400:
            self.samples = self.samples[-400:]

    def _duration_unlocked(self, now: float) -> float | None:
        if self.started_monotonic is None:
            return None
        end = self.finished_monotonic if self.finished_monotonic is not None else now
        return max(0.0, end - self.started_monotonic)

    def _average_throughput_unlocked(self, duration: float | None) -> float | None:
        if duration is None or duration <= 0:
            return None
        if self.status == "queued":
            return None
        return self.bytes_acked / duration

    def _current_throughput_unlocked(self) -> float | None:
        if len(self.samples) < 2:
            return None
        latest = self.samples[-1]
        earlier = None
        for sample in reversed(self.samples):
            if latest["t"] - sample["t"] >= 1.0:
                earlier = sample
                break
        if earlier is None:
            earlier = self.samples[0]
        dt = latest["t"] - earlier["t"]
        if dt <= 0.05:
            return None
        return (latest["bytes"] - earlier["bytes"]) / dt

    def _simulator_unlocked(self) -> dict:
        dropped = corrupted = attempted = 0
        delay_ms = 0.0
        data_attempted = data_dropped = 0
        parts: dict[str, dict | None] = {}
        for name, simulator in (
            ("sender", self.sender_simulator),
            ("receiver", self.receiver_simulator),
        ):
            if simulator is None:
                parts[name] = None
                continue
            stats = simulator.stats()
            parts[name] = stats
            attempted += stats["attempted"]
            dropped += stats["dropped"]
            corrupted += stats["corrupted"]
            delay_ms += stats["total_delay_ms"]
            for category, bucket in stats["categories"].items():
                if category == "data" or category == "data_retransmission":
                    data_attempted += bucket["attempted"]
                    data_dropped += bucket["dropped"]
        return {
            "attempted": attempted,
            "dropped": dropped,
            "corrupted": corrupted,
            "total_delay_ms": round(delay_ms, 3),
            "drop_rate": (dropped / attempted) if attempted else None,
            "data_attempted": data_attempted,
            "data_dropped": data_dropped,
            "data_drop_rate": (data_dropped / data_attempted) if data_attempted else None,
            "by_direction": parts,
        }

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            duration = self._duration_unlocked(now)
            average = self._average_throughput_unlocked(duration)
            simulator = self._simulator_unlocked()
            attempts = self.data_transmissions
            return {
                "status": self.status,
                "error": self.error,
                "integrity": self.integrity,
                "protocol": self.protocol,
                "window_size": self.window_size,
                "chunk_size": self.chunk_size,
                "ack_timeout_ms": self.ack_timeout_ms,
                "max_retries": self.max_retries,
                "loss_percent": self.loss_percent,
                "delay_ms": self.delay_ms,
                "corruption_percent": self.corruption_percent,
                "file_size": self.file_size,
                "bytes_acked": self.bytes_acked,
                "progress": round(self._progress_unlocked(), 2),
                "duration_seconds": None if duration is None else round(duration, 6),
                "average_throughput_bps": None if average is None else round(average, 3),
                "current_throughput_bps": (
                    None
                    if (current := self._current_throughput_unlocked()) is None
                    else round(current, 3)
                ),
                "average_rtt_ms": (
                    None if self.rtt_count == 0 else round((self.rtt_sum / self.rtt_count) * 1000.0, 3)
                ),
                "min_rtt_ms": None if self.rtt_min is None else round(self.rtt_min * 1000.0, 3),
                "max_rtt_ms": None if self.rtt_max is None else round(self.rtt_max * 1000.0, 3),
                "rtt_samples": self.rtt_count,
                "original_data_packets": self.total_chunks,
                "packets_acked": self.packets_acked,
                "transmission_attempts": attempts,
                "retransmissions": self.retransmissions,
                "retransmitted_sequences": list(self.retransmitted_sequences[-200:]),
                "control_transmissions": self.control_transmissions,
                "control_retries": self.control_retries,
                "duplicate_acks": self.duplicate_acks,
                "invalid_packets": self.invalid_packets,
                "effective_retransmission_rate": (self.retransmissions / attempts) if attempts else None,
                "expected_sha256": self.expected_sha256,
                "received_sha256": self.received_sha256,
                "simulator": simulator,
                "samples": list(self.samples),
                "events": self.events.recent(12),
            }
