"""Injectable loss, corruption, and delay for outgoing UDP datagrams.

The simulator does not parse packet contents. Callers label each datagram with
a category such as ``data`` or ``ack``. A datagram is dropped or corrupted
before it is handed to the socket. Dropped datagrams are not transmitted.

Artificial delay is applied on the sending thread before ``sendto``, and is a
random value between 50% and 100% of the configured delay so successive
packets show timing variation while remaining inside the configured bound.
"""

from __future__ import annotations

import random
import threading
import time
from collections import defaultdict
from typing import Callable


def corrupt_datagram(datagram: bytes, rng: random.Random) -> bytes:
    """Return a copy with one bit flipped so a CRC32 check will fail."""
    if not datagram:
        return b"\xff"
    buffer = bytearray(datagram)
    index = rng.randrange(len(buffer))
    buffer[index] ^= 1 << rng.randrange(8)
    return bytes(buffer)


class NetworkSimulator:
    def __init__(
        self,
        loss_probability: float = 0.0,
        corruption_probability: float = 0.0,
        delay_ms: float = 0.0,
        seed: int | None = None,
        drop_predicate: Callable[[bytes], bool] | None = None,
        corrupt_predicate: Callable[[bytes], bool] | None = None,
    ) -> None:
        if not 0.0 <= loss_probability <= 1.0:
            raise ValueError("loss probability must be between 0 and 1")
        if not 0.0 <= corruption_probability <= 1.0:
            raise ValueError("corruption probability must be between 0 and 1")
        if delay_ms < 0:
            raise ValueError("delay must be non-negative")
        self.loss_probability = float(loss_probability)
        self.corruption_probability = float(corruption_probability)
        self.delay_ms = float(delay_ms)
        self.seed = seed
        self.drop_predicate = drop_predicate
        self.corrupt_predicate = corrupt_predicate
        self.rng = random.Random(seed)
        self._lock = threading.Lock()
        self.attempted = 0
        self.dropped = 0
        self.corrupted = 0
        self.delay_events = 0
        self.total_delay_ms = 0.0
        self._categories: dict[str, dict[str, int]] = defaultdict(
            lambda: {"attempted": 0, "dropped": 0, "corrupted": 0}
        )

    @classmethod
    def from_percents(
        cls,
        loss_percent: float = 0.0,
        corruption_percent: float = 0.0,
        delay_ms: float = 0.0,
        seed: int | None = None,
    ) -> NetworkSimulator:
        return cls(
            loss_probability=loss_percent / 100.0,
            corruption_probability=corruption_percent / 100.0,
            delay_ms=delay_ms,
            seed=seed,
        )

    def process(self, datagram: bytes, category: str = "unknown") -> bytes | None:
        """Return the datagram to transmit, or None when it is dropped."""
        drop = False
        if self.drop_predicate is not None and self.drop_predicate(datagram):
            drop = True
        elif self.loss_probability > 0 and self.rng.random() < self.loss_probability:
            drop = True

        corrupted = False
        outgoing = datagram
        if not drop:
            if self.corrupt_predicate is not None and self.corrupt_predicate(datagram):
                outgoing = corrupt_datagram(datagram, self.rng)
                corrupted = True
            elif self.corruption_probability > 0 and self.rng.random() < self.corruption_probability:
                outgoing = corrupt_datagram(datagram, self.rng)
                corrupted = True

        delay_s = 0.0
        if self.delay_ms > 0:
            delay_s = self.rng.uniform(0.5 * self.delay_ms, self.delay_ms) / 1000.0

        with self._lock:
            self.attempted += 1
            bucket = self._categories[category]
            bucket["attempted"] += 1
            if drop:
                self.dropped += 1
                bucket["dropped"] += 1
            elif corrupted:
                self.corrupted += 1
                bucket["corrupted"] += 1
            if delay_s > 0:
                self.delay_events += 1
                self.total_delay_ms += delay_s * 1000.0

        if drop:
            if delay_s > 0:
                time.sleep(delay_s)
            return None
        if delay_s > 0:
            time.sleep(delay_s)
        return outgoing

    def stats(self) -> dict:
        with self._lock:
            attempted = self.attempted
            dropped = self.dropped
            return {
                "attempted": attempted,
                "dropped": dropped,
                "corrupted": self.corrupted,
                "delay_events": self.delay_events,
                "total_delay_ms": round(self.total_delay_ms, 3),
                "drop_rate": (dropped / attempted) if attempted else None,
                "categories": {key: dict(value) for key, value in self._categories.items()},
            }
