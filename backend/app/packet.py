"""Binary ReliableUDP packet codec.

Header layout, big-endian (network byte order), 48 bytes:

    magic            4s   b'RUDP'
    version          B
    packet_type      B
    flags            H
    transfer_id      16s  UUID bytes
    sequence         Q    unsigned 64-bit, data sequences start at 0
    acknowledgement  Q    unsigned 64-bit
    payload_length   I
    crc32            I    IEEE CRC32 over the header with this field zeroed, plus payload

ACK acknowledgement numbers are cumulative: the value is the next sequence
number the receiver expects, so every sequence below it has been accepted.

SACK acknowledgement numbers name one accepted sequence number.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"RUDP"
VERSION = 1
HEADER_STRUCT = struct.Struct(">4sBBH16sQQII")
HEADER_SIZE = HEADER_STRUCT.size

FLAG_RETRANSMIT = 0x0001


class PacketType(IntEnum):
    START = 1
    READY = 2
    DATA = 3
    ACK = 4
    SACK = 5
    FIN = 6
    FIN_ACK = 7
    ERROR = 8


class PacketError(ValueError):
    """Raised when a datagram is not a valid ReliableUDP packet."""


@dataclass
class Packet:
    packet_type: PacketType
    transfer_id: bytes
    seq: int = 0
    ack: int = 0
    flags: int = 0
    payload: bytes = b""
    version: int = VERSION

    def encode(self) -> bytes:
        if len(self.transfer_id) != 16:
            raise PacketError("transfer id must be 16 bytes")
        if not 0 <= int(self.packet_type) <= 255:
            raise PacketError("invalid packet type")
        payload = bytes(self.payload)
        if len(payload) > 0xFFFFFFFF:
            raise PacketError("payload too large")
        checksum = checksum_for(
            self.version,
            int(self.packet_type),
            self.flags,
            self.transfer_id,
            self.seq,
            self.ack,
            payload,
        )
        header = HEADER_STRUCT.pack(
            MAGIC,
            self.version,
            int(self.packet_type),
            self.flags,
            self.transfer_id,
            self.seq,
            self.ack,
            len(payload),
            checksum,
        )
        return header + payload


def checksum_for(
    version: int,
    packet_type: int,
    flags: int,
    transfer_id: bytes,
    seq: int,
    ack: int,
    payload: bytes,
) -> int:
    header = HEADER_STRUCT.pack(
        MAGIC,
        version,
        packet_type,
        flags,
        transfer_id,
        seq,
        ack,
        len(payload),
        0,
    )
    return zlib.crc32(header + payload) & 0xFFFFFFFF


def decode(data: bytes) -> Packet:
    if not isinstance(data, (bytes, bytearray)):
        raise PacketError("datagram must be bytes")
    data = bytes(data)
    if len(data) < HEADER_SIZE:
        raise PacketError("truncated header")
    magic, version, packet_type, flags, transfer_id, seq, ack, length, crc = HEADER_STRUCT.unpack(
        data[:HEADER_SIZE]
    )
    if magic != MAGIC:
        raise PacketError("invalid magic identifier")
    if version != VERSION:
        raise PacketError("unsupported packet version")
    if packet_type not in PacketType._value2member_map_:
        raise PacketError("invalid packet type")
    payload = data[HEADER_SIZE:]
    if length != len(payload):
        raise PacketError("incorrect payload length")
    expected = checksum_for(version, packet_type, flags, transfer_id, seq, ack, payload)
    if expected != crc:
        raise PacketError("checksum mismatch")
    return Packet(
        packet_type=PacketType(packet_type),
        transfer_id=transfer_id,
        seq=seq,
        ack=ack,
        flags=flags,
        payload=payload,
        version=version,
    )


def send_category(packet_type: PacketType, retransmit: bool = False) -> str:
    if packet_type == PacketType.DATA:
        return "data_retransmission" if retransmit else "data"
    if packet_type == PacketType.ACK:
        return "ack"
    if packet_type == PacketType.SACK:
        return "sack"
    return "control"
