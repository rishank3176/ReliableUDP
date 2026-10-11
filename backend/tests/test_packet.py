import uuid

import pytest

from app.packet import (
    HEADER_SIZE,
    MAGIC,
    VERSION,
    Packet,
    PacketError,
    PacketType,
    decode,
)


def _packet(**kwargs) -> Packet:
    values = {
        "packet_type": PacketType.DATA,
        "transfer_id": uuid.uuid4().bytes,
        "seq": 0,
        "ack": 0,
        "payload": b"abc",
    }
    values.update(kwargs)
    return Packet(**values)


def test_header_size_is_48_bytes():
    assert HEADER_SIZE == 48


def test_round_trip_preserves_fields_and_binary_payload():
    payload = bytes(range(256)) + b"\x00\xff binary"
    original = _packet(seq=2**40, ack=99, payload=payload, flags=1)
    decoded = decode(original.encode())
    assert decoded.packet_type == PacketType.DATA
    assert decoded.transfer_id == original.transfer_id
    assert decoded.seq == 2**40
    assert decoded.ack == 99
    assert decoded.flags == 1
    assert decoded.payload == payload
    assert decoded.version == VERSION


def test_empty_payload_round_trip():
    original = _packet(packet_type=PacketType.ACK, payload=b"", ack=4, seq=0)
    decoded = decode(original.encode())
    assert decoded.payload == b""
    assert decoded.ack == 4
    assert decoded.packet_type == PacketType.ACK


def test_checksum_detects_corruption():
    raw = bytearray(_packet(payload=b"intact").encode())
    raw[-1] ^= 0x01
    with pytest.raises(PacketError, match="checksum"):
        decode(bytes(raw))


def test_invalid_magic():
    raw = bytearray(_packet().encode())
    raw[0:4] = b"NOPE"
    with pytest.raises(PacketError, match="magic"):
        decode(bytes(raw))


def test_unsupported_version():
    raw = bytearray(_packet().encode())
    raw[4] = VERSION + 1
    with pytest.raises(PacketError, match="version"):
        decode(bytes(raw))


def test_invalid_packet_type():
    raw = bytearray(_packet().encode())
    raw[5] = 99
    with pytest.raises(PacketError, match="packet type"):
        decode(bytes(raw))


def test_incorrect_payload_length():
    raw = bytearray(_packet(payload=b"1234").encode())
    raw.append(0xAB)
    with pytest.raises(PacketError, match="payload length"):
        decode(bytes(raw))


def test_truncated_header():
    with pytest.raises(PacketError, match="truncated"):
        decode(MAGIC + b"\x01")


def test_magic_constant():
    assert MAGIC == b"RUDP"
