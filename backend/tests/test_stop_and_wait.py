import uuid

from app.network_simulator import NetworkSimulator
from app.packet import PacketType, decode

from helpers import run_transfer


def _send_events(metrics):
    return [event for event in metrics.events.list() if event["kind"] == "send"]


def test_lossless_transfer_uses_a_window_of_one(tmp_path):
    payload = b"stop-and-wait-demo-0123456789" * 8
    result = run_transfer(
        tmp_path,
        payload,
        "stop_and_wait",
        window_size=8,
        chunk_size=64,
        ack_timeout_ms=400,
    )
    snapshot = result["snapshot"]
    assert snapshot["status"] == "completed"
    assert snapshot["integrity"] == "verified"
    assert snapshot["window_size"] == 1
    assert snapshot["retransmissions"] == 0
    assert snapshot["average_rtt_ms"] is not None
    assert result["output"].read_bytes() == payload
    events = result["metrics"].events.list()
    first_ack = next(index for index, event in enumerate(events) if event["kind"] == "ack")
    sends_before_ack = [event for event in events[:first_ack] if event["kind"] == "send"]
    assert len(sends_before_ack) == 1
    assert len(_send_events(result["metrics"])) == snapshot["original_data_packets"]


def test_recovers_from_a_lost_data_packet(tmp_path):
    dropped = {"done": False}

    def drop_first_data(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        if packet and packet.packet_type == PacketType.DATA and packet.seq == 0 and not dropped["done"]:
            dropped["done"] = True
            return True
        return False

    payload = b"abcdefghijklmnopqrstuvwxyz"
    result = run_transfer(
        tmp_path,
        payload,
        "stop_and_wait",
        chunk_size=64,
        ack_timeout_ms=200,
        max_retries=4,
        sender_simulator=NetworkSimulator(drop_predicate=drop_first_data),
    )
    assert result["snapshot"]["status"] == "completed"
    assert result["snapshot"]["retransmissions"] >= 1
    assert 0 in result["snapshot"]["retransmitted_sequences"]
    assert result["output"].read_bytes() == payload


def test_recovers_from_a_lost_acknowledgement(tmp_path):
    dropped = {"done": False}

    def drop_first_ack(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        if packet and packet.packet_type == PacketType.ACK and not dropped["done"]:
            dropped["done"] = True
            return True
        return False

    payload = b"ack-loss"
    result = run_transfer(
        tmp_path,
        payload,
        "stop_and_wait",
        chunk_size=64,
        ack_timeout_ms=200,
        max_retries=4,
        receiver_simulator=NetworkSimulator(drop_predicate=drop_first_ack),
    )
    assert result["snapshot"]["status"] == "completed"
    assert result["snapshot"]["retransmissions"] >= 1
    assert result["output"].read_bytes() == payload


def test_recovers_from_corruption(tmp_path):
    corrupted = {"done": False}

    def corrupt_first_data(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        if packet and packet.packet_type == PacketType.DATA and not corrupted["done"]:
            corrupted["done"] = True
            return True
        return False

    payload = b"corrupt-me-please"
    result = run_transfer(
        tmp_path,
        payload,
        "stop_and_wait",
        chunk_size=64,
        ack_timeout_ms=200,
        max_retries=4,
        sender_simulator=NetworkSimulator(corrupt_predicate=corrupt_first_data, seed=1),
    )
    assert result["snapshot"]["status"] == "completed"
    assert result["snapshot"]["simulator"]["corrupted"] >= 1
    assert result["receiver"].invalid_packets >= 1
    assert result["output"].read_bytes() == payload


def test_retry_limit_fails_the_transfer(tmp_path):
    def drop_data(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        return bool(packet and packet.packet_type == PacketType.DATA)

    result = run_transfer(
        tmp_path,
        b"never",
        "stop_and_wait",
        chunk_size=64,
        ack_timeout_ms=40,
        max_retries=1,
        sender_simulator=NetworkSimulator(drop_predicate=drop_data),
    )
    assert result["snapshot"]["status"] == "failed"
    assert "Retry limit" in result["snapshot"]["error"]
    assert result["snapshot"]["integrity"] != "verified"
    assert not result["output"].exists()


def _try_decode(datagram: bytes):
    try:
        return decode(datagram)
    except Exception:
        return None
