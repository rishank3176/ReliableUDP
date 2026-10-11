"""UDP receiver. Reconstructs files and acknowledges them.

Run a standalone receiver with:

    python -m app.receiver --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from .config import PROJECT_ROOT
from .file_manager import FileMetadata, FileReassembler, output_paths
from .network_simulator import NetworkSimulator
from .packet import Packet, PacketError, PacketType, decode, send_category
from .protocols.common import control_packet
from .protocols.go_back_n import GoBackNReceiver
from .protocols.selective_repeat import SelectiveRepeatReceiver
from .protocols.stop_and_wait import StopAndWaitReceiver
from .transport import bind_udp

logger = logging.getLogger("reliableudp.receiver")

_SESSIONS = {
    "stop_and_wait": StopAndWaitReceiver,
    "go_back_n": GoBackNReceiver,
    "selective_repeat": SelectiveRepeatReceiver,
}


class UdpReceiver:
    def __init__(
        self,
        host: str,
        port: int,
        output_dir: Path,
        simulator: NetworkSimulator | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.simulator = simulator
        self.sock = None
        self.bind_error: str | None = None
        self.bound_host: str | None = None
        self.bound_port: int | None = None
        self.invalid_packets = 0
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sim_lock = threading.Lock()
        self.sessions: dict[bytes, object] = {}

    def set_simulator(self, simulator: NetworkSimulator | None) -> None:
        with self._sim_lock:
            self.simulator = simulator

    def _current_simulator(self) -> NetworkSimulator | None:
        with self._sim_lock:
            return self.simulator

    def start_background(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="reliableudp-receiver", daemon=True)
        self._thread.start()
        self.ready.wait(timeout=3)

    def stop(self) -> None:
        self._stop.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def serve_forever(self) -> None:
        try:
            self.sock = bind_udp(self.host, self.port)
        except OSError as exc:
            self.bind_error = f"Could not bind UDP {self.host}:{self.port} ({exc.strerror or exc})"
            logger.error(self.bind_error)
            self.ready.set()
            return
        self.bound_host, self.bound_port = self.sock.getsockname()[:2]
        logger.info("UDP receiver listening on %s:%s", self.bound_host, self.bound_port)
        self.ready.set()
        try:
            while not self._stop.is_set():
                self._receive_once()
        finally:
            sock = self.sock
            self.sock = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _receive_once(self) -> None:
        sock = self.sock
        if sock is None:
            return
        import select

        try:
            readable, _, _ = select.select([sock], [], [], 0.5)
        except OSError:
            return
        if not readable or self._stop.is_set():
            return
        try:
            data, addr = sock.recvfrom(65535)
        except OSError:
            return
        try:
            packet = decode(data)
        except PacketError as exc:
            self.invalid_packets += 1
            logger.debug("Dropped invalid datagram from %s: %s", addr, exc)
            return
        try:
            self._dispatch(packet, addr)
        except Exception:
            logger.exception("Receiver failed while handling packet type %s", packet.packet_type)
            self._send(
                control_packet(
                    PacketType.ERROR,
                    packet.transfer_id,
                    {"message": "Receiver could not process the packet"},
                ),
                addr,
                False,
            )

    def _dispatch(self, packet: Packet, addr) -> None:
        if packet.packet_type == PacketType.START:
            self._on_start(packet, addr)
            return
        session = self.sessions.get(packet.transfer_id)
        if session is None:
            logger.debug("Ignoring %s for unknown transfer", packet.packet_type.name)
            return
        if packet.packet_type == PacketType.ERROR:
            session.writer.abort()
            return
        session.handle(packet, addr)

    def _on_start(self, packet: Packet, addr) -> None:
        existing = self.sessions.get(packet.transfer_id)
        if existing is not None:
            existing.handle(packet, addr)
            return
        try:
            meta = FileMetadata.from_payload(packet.payload)
        except ValueError as exc:
            self._send(
                control_packet(PacketType.ERROR, packet.transfer_id, {"message": str(exc)}),
                addr,
                False,
            )
            return
        transfer_hex = packet.transfer_id.hex()
        partial, final = output_paths(self.output_dir, transfer_hex, meta.filename)
        if final.exists():
            final = final.with_name(f"{final.stem}_{transfer_hex[:8]}{final.suffix}")
            partial = partial.with_name(f".{final.name}.partial")
        try:
            writer = FileReassembler(partial, final, meta, transfer_hex)
        except OSError as exc:
            logger.error("Could not create output file: %s", exc)
            self._send(
                control_packet(
                    PacketType.ERROR,
                    packet.transfer_id,
                    {"message": "Receiver could not create the output file"},
                ),
                addr,
                False,
            )
            return
        session_cls = _SESSIONS[meta.protocol]
        session = session_cls(meta, writer, self._send, packet.transfer_id)
        self._prune_sessions()
        self.sessions[packet.transfer_id] = session
        logger.info(
            "Accepted %s transfer %s (%s bytes, %s)",
            meta.protocol,
            transfer_hex,
            meta.file_size,
            meta.filename,
        )
        session.handle(packet, addr)

    def _prune_sessions(self) -> None:
        if len(self.sessions) < 40:
            return
        finished = [key for key, session in self.sessions.items() if session.final_response is not None]
        for key in finished[:20]:
            self.sessions.pop(key, None)

    def _send(self, packet: Packet, addr, retransmit: bool) -> None:
        raw = packet.encode()
        simulator = self._current_simulator()
        if simulator is not None:
            processed = simulator.process(raw, category=send_category(packet.packet_type, retransmit))
            if processed is None:
                return
            raw = processed
        sock = self.sock
        if sock is None:
            return
        try:
            sock.sendto(raw, addr)
        except OSError:
            logger.warning("Failed to send %s", packet.packet_type.name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ReliableUDP standalone receiver")
    parser.add_argument("--host", default="0.0.0.0", help="Address to bind (use 0.0.0.0 for other computers)")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "received_files"),
        help="Directory for reconstructed files",
    )
    parser.add_argument("--loss", type=float, default=0.0, help="Outgoing ACK/control loss percent")
    parser.add_argument("--corruption", type=float, default=0.0, help="Outgoing corruption percent")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Artificial delay bound in milliseconds")
    parser.add_argument("--seed", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    simulator = None
    if args.loss or args.corruption or args.delay_ms:
        simulator = NetworkSimulator.from_percents(args.loss, args.corruption, args.delay_ms, args.seed)
    receiver = UdpReceiver(args.host, args.port, Path(args.output), simulator)
    try:
        receiver.serve_forever()
    except KeyboardInterrupt:
        logger.info("Receiver stopped")
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()
