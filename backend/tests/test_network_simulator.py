import random

import pytest

from app.network_simulator import NetworkSimulator, corrupt_datagram
from app.packet import PacketError, decode


def test_total_loss_drops_every_datagram():
    simulator = NetworkSimulator(loss_probability=1.0, seed=1)
    assert simulator.process(b"abc", category="data") is None
    assert simulator.process(b"def", category="ack") is None
    stats = simulator.stats()
    assert stats["attempted"] == 2
    assert stats["dropped"] == 2
    assert stats["drop_rate"] == 1.0
    assert stats["categories"]["data"]["dropped"] == 1
    assert stats["categories"]["ack"]["dropped"] == 1


def test_zero_loss_delivers_unchanged_bytes():
    simulator = NetworkSimulator(loss_probability=0.0, corruption_probability=0.0, seed=2)
    delivered = simulator.process(b"payload", category="data")
    assert delivered == b"payload"
    assert simulator.stats()["dropped"] == 0
    assert simulator.stats()["corrupted"] == 0


def test_loss_rate_is_statistical_and_seeded_runs_match():
    def count(seed: int) -> int:
        simulator = NetworkSimulator(loss_probability=0.5, seed=seed)
        drops = 0
        for index in range(2000):
            if simulator.process(f"packet-{index}".encode(), category="data") is None:
                drops += 1
        return drops

    first = count(12345)
    second = count(12345)
    assert first == second
    assert 800 <= first <= 1200


def test_corruption_changes_bytes_and_breaks_crc():
    from app.packet import Packet, PacketType
    import uuid

    packet = Packet(PacketType.DATA, uuid.uuid4().bytes, seq=1, payload=b"hello reliable udp")
    raw = packet.encode()
    simulator = NetworkSimulator(corruption_probability=1.0, seed=7)
    corrupted = simulator.process(raw, category="data")
    assert corrupted is not None
    assert corrupted != raw
    assert simulator.stats()["corrupted"] == 1
    with pytest.raises(PacketError, match="checksum"):
        decode(corrupted)


def test_corrupt_datagram_flips_a_bit():
    original = b"\x00" * 16
    changed = corrupt_datagram(original, random.Random(1))
    assert changed != original
    assert len(changed) == len(original)


def test_delay_is_applied_inside_the_configured_bound():
    simulator = NetworkSimulator(delay_ms=40, seed=3)
    import time

    started = time.monotonic()
    delivered = simulator.process(b"delayed", category="data")
    elapsed_ms = (time.monotonic() - started) * 1000
    assert delivered == b"delayed"
    assert elapsed_ms >= 18
    stats = simulator.stats()
    assert stats["delay_events"] == 1
    assert 20 <= stats["total_delay_ms"] <= 40.1


def test_predicate_can_force_a_drop_without_parsing_inside_the_simulator():
    seen = []

    def drop_first(datagram: bytes) -> bool:
        seen.append(datagram)
        return len(seen) == 1

    simulator = NetworkSimulator(drop_predicate=drop_first)
    assert simulator.process(b"one") is None
    assert simulator.process(b"two") == b"two"
    assert simulator.stats()["dropped"] == 1
