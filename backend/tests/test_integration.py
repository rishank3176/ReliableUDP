import hashlib
import socket
import threading
import time
import uuid

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.packet import Packet, PacketType, decode
from app.transport import bind_udp

from helpers import run_transfer


PROTOCOLS = ("stop_and_wait", "go_back_n", "selective_repeat")


def test_all_protocols_transfer_binary_and_empty_files(tmp_path):
    binary = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) + b"\x00\xff" * 30
    cases = [b"", b"hi", binary, b"Z" * 5000]
    for protocol in PROTOCOLS:
        for payload in cases:
            result = run_transfer(
                tmp_path / f"{protocol}-{len(payload)}",
                payload,
                protocol,
                window_size=5,
                chunk_size=300,
                ack_timeout_ms=400,
                filename="demo.bin",
            )
            assert result["snapshot"]["status"] == "completed", result["snapshot"]
            assert result["snapshot"]["integrity"] == "verified"
            assert result["output"].read_bytes() == payload
            assert result["snapshot"]["received_sha256"] == hashlib.sha256(payload).hexdigest()


def test_controlled_loss_and_corruption_still_reconstruct_the_file(tmp_path):
    payload = b"recover-this-binary" * 40
    result = run_transfer(
        tmp_path,
        payload,
        "selective_repeat",
        window_size=6,
        chunk_size=128,
        ack_timeout_ms=200,
        max_retries=15,
        loss_percent=10,
        corruption_percent=5,
        seed=99,
    )
    assert result["snapshot"]["status"] == "completed", result["snapshot"]
    assert result["output"].read_bytes() == payload
    assert result["snapshot"]["simulator"]["dropped"] + result["snapshot"]["simulator"]["corrupted"] > 0


def test_completion_requires_receiver_confirmation(tmp_path):
    """A peer that never sends FIN_ACK must not be reported as successful."""
    sock = bind_udp("127.0.0.1", 0)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            sock.settimeout(0.2)
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                packet = decode(data)
            except Exception:
                continue
            if packet.packet_type == PacketType.START:
                reply = Packet(PacketType.READY, packet.transfer_id, payload=b'{"ok":true}')
                sock.sendto(reply.encode(), addr)
            elif packet.packet_type == PacketType.DATA:
                reply = Packet(PacketType.ACK, packet.transfer_id, ack=packet.seq + 1)
                sock.sendto(reply.encode(), addr)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    source = tmp_path / "file.bin"
    source.write_bytes(b"needs-confirmation")
    from app.metrics import Metrics
    from app.models import TransferParams
    from app.sender import perform_transfer
    from app.transport import TransferError

    metrics = Metrics()
    params = TransferParams(
        protocol="stop_and_wait",
        window_size=1,
        chunk_size=64,
        ack_timeout_ms=50,
        max_retries=1,
        receiver_host="127.0.0.1",
        receiver_port=port,
    )
    try:
        try:
            perform_transfer(source, params, metrics, transfer_id=uuid.uuid4().bytes, original_name="file.bin")
        except TransferError as exc:
            metrics.mark_failed(str(exc))
        else:
            metrics.mark_completed()
        snapshot = metrics.snapshot()
        assert snapshot["status"] == "failed"
        assert snapshot["integrity"] != "verified"
    finally:
        stop.set()
        sock.close()
        thread.join(timeout=1)


def test_api_health_transfer_download_and_benchmark(tmp_path):
    settings = Settings(
        udp_host="127.0.0.1",
        udp_port=0,
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "received",
        local_receiver=True,
        max_upload_bytes=1024 * 1024,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["api"] == "ok"
        assert body["udp_receiver"]["running"] is True
        port = body["udp_receiver"]["port"]
        config = client.get("/api/config")
        assert config.status_code == 200
        assert len(config.json()["protocols"]) == 3

        rejected = client.post(
            "/api/transfers",
            data={"protocol": "tcp", "receiver_port": str(port)},
            files={"file": ("a.txt", b"abc", "application/octet-stream")},
        )
        assert rejected.status_code == 422

        payload = b"\x00\x01api-transfer\xff"
        started = client.post(
            "/api/transfers",
            data={
                "protocol": "go_back_n",
                "window_size": "4",
                "chunk_size": "64",
                "ack_timeout_ms": "400",
                "max_retries": "5",
                "receiver_host": "127.0.0.1",
                "receiver_port": str(port),
                "loss_percent": "0",
                "delay_ms": "0",
                "corruption_percent": "0",
            },
            files={"file": ("notes.bin", payload, "application/octet-stream")},
        )
        assert started.status_code == 201, started.text
        transfer_id = started.json()["id"]
        deadline = time.monotonic() + 8
        view = started.json()
        while view["status"] not in {"completed", "failed", "cancelled"} and time.monotonic() < deadline:
            time.sleep(0.05)
            view = client.get(f"/api/transfers/{transfer_id}").json()
        assert view["status"] == "completed", view
        assert view["integrity"] == "verified"
        assert view["received_sha256"] == hashlib.sha256(payload).hexdigest()
        downloaded = client.get(f"/api/transfers/{transfer_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == payload
        listing = client.get("/api/transfers").json()
        assert any(item["id"] == transfer_id for item in listing["transfers"])
        received = client.get("/api/received-files").json()
        assert any(item["verified"] and item["size"] == len(payload) for item in received["files"])
        missing = client.get("/api/transfers/does-not-exist")
        assert missing.status_code == 404

        benchmark = client.post(
            "/api/benchmark",
            data={
                "receiver_host": "127.0.0.1",
                "receiver_port": str(port),
                "window_size": "4",
                "chunk_size": "256",
                "ack_timeout_ms": "400",
                "max_retries": "4",
                "generate_bytes": "2048",
            },
            files={"file": ("bench.bin", b"benchmark-payload", "application/octet-stream")},
        )
        assert benchmark.status_code == 202, benchmark.text
        benchmark_id = benchmark.json()["id"]
        deadline = time.monotonic() + 20
        current = benchmark.json()
        while current["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.1)
            current = client.get(f"/api/benchmark/{benchmark_id}").json()
        assert current["status"] == "completed", current
        assert [row["protocol"] for row in current["results"]] == list(PROTOCOLS)
        assert all(row["status"] == "completed" and row["integrity"] == "verified" for row in current["results"])
        latest = client.get("/api/benchmark").json()
        assert latest["benchmark"]["id"] == benchmark_id


def test_cancel_prevents_success(tmp_path):
    settings = Settings(
        udp_host="127.0.0.1",
        udp_port=0,
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "received",
        local_receiver=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        port = client.get("/api/health").json()["udp_receiver"]["port"]
        started = client.post(
            "/api/transfers",
            data={
                "protocol": "stop_and_wait",
                "window_size": "1",
                "chunk_size": "64",
                "ack_timeout_ms": "1000",
                "max_retries": "2",
                "receiver_host": "127.0.0.1",
                "receiver_port": str(port),
                "delay_ms": "250",
            },
            files={"file": ("slow.bin", b"x" * 800, "application/octet-stream")},
        )
        assert started.status_code == 201, started.text
        transfer_id = started.json()["id"]
        cancelled = client.post(f"/api/transfers/{transfer_id}/cancel")
        assert cancelled.status_code == 200
        deadline = time.monotonic() + 8
        view = cancelled.json()
        while view["status"] not in {"completed", "failed", "cancelled"} and time.monotonic() < deadline:
            time.sleep(0.05)
            view = client.get(f"/api/transfers/{transfer_id}").json()
        assert view["status"] == "cancelled"
        assert view["integrity"] != "verified"
        download = client.get(f"/api/transfers/{transfer_id}/download")
        assert download.status_code == 409
