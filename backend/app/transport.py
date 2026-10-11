"""UDP peer helpers shared by the sender protocols."""

from __future__ import annotations

import errno
import json
import select
import socket
import threading
import time

from .metrics import Metrics
from .network_simulator import NetworkSimulator
from .packet import Packet, PacketError, PacketType, decode, send_category

_BAD_PACKET = object()


class TransferError(Exception):
    """A transfer failed for a reason that can be shown to the user."""


class TransferCancelled(Exception):
    """The caller cancelled the transfer."""


def bind_udp(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TransferCancelled()


class Peer:
    """Sends encoded packets through an optional simulator and receives replies."""

    def __init__(
        self,
        sock: socket.socket,
        addr: tuple[str, int],
        transfer_id: bytes,
        simulator: NetworkSimulator | None = None,
        cancel_event: threading.Event | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.sock = sock
        self.addr = addr
        self.transfer_id = transfer_id
        self.simulator = simulator
        self.cancel_event = cancel_event
        self.metrics = metrics

    def send(self, packet: Packet, retransmit: bool = False) -> bool:
        raw = packet.encode()
        if self.simulator is not None:
            processed = self.simulator.process(raw, category=send_category(packet.packet_type, retransmit))
            if processed is None:
                return False
            raw = processed
        self.sock.sendto(raw, self.addr)
        return True

    def recv_matching(self, timeout: float, predicate) -> Packet | None:
        """Return the next matching packet, or None when the wait expires.

        A timeout of 0 drains packets that are already buffered without waiting.
        Checksum failures and unrelated packets do not extend a positive timeout.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        drains = 0
        while True:
            raise_if_cancelled(self.cancel_event)
            now = time.monotonic()
            if timeout > 0 and now >= deadline:
                return None
            wait = 0.0 if timeout <= 0 else min(0.2, deadline - now)
            packet = self._recv_one(wait)
            if packet is None:
                return None
            if packet is _BAD_PACKET:
                if timeout <= 0:
                    drains += 1
                    if drains >= 100:
                        return None
                continue
            if packet.packet_type == PacketType.ERROR and packet.transfer_id == self.transfer_id:
                message = _error_message(packet)
                raise TransferError(message)
            if packet.transfer_id == self.transfer_id and predicate(packet):
                return packet
            drains += 1
            if timeout <= 0 and drains >= 100:
                return None
            if timeout <= 0 and packet is not None:
                continue

    def _recv_one(self, timeout: float) -> Packet | None:
        readable, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        if not readable:
            return None
        try:
            data, _addr = self.sock.recvfrom(65535)
        except (socket.timeout, TimeoutError, ConnectionRefusedError):
            return None
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNREFUSED, errno.EBADF}:
                return None
            raise
        try:
            return decode(data)
        except PacketError:
            if self.metrics is not None:
                self.metrics.note_invalid()
            return _BAD_PACKET


def _error_message(packet: Packet) -> str:
    try:
        body = json.loads(packet.payload.decode("utf-8")) if packet.payload else {}
        message = str(body.get("message") or "receiver reported an error")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        message = "receiver reported an error"
    return message[:300]
