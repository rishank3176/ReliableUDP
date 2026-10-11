"""Thread-safe transfer event log."""

from __future__ import annotations

import threading
import time
from typing import Any


class EventLog:
    def __init__(self, limit: int = 200) -> None:
        self._limit = limit
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._origin = time.monotonic()

    def add(self, kind: str, message: str, **fields: Any) -> None:
        event = {
            "t": round(time.monotonic() - self._origin, 3),
            "kind": kind,
            "message": message,
            **fields,
        }
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._limit:
                self._events = self._events[-self._limit :]

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def recent(self, count: int = 12) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[-count:])
