import json
import uuid

from app.file_manager import FileMetadata, FileReassembler, output_paths, sha256_bytes
from app.network_simulator import NetworkSimulator
from app.packet import Packet, PacketType, decode
from app.protocols.selective_repeat import SelectiveRepeatReceiver

from helpers import run_transfer


def test_multi_packet_window_completes(tmp_path):
    payload = bytes(range(256)) * 5
    result = run_transfer(
        tmp_path,
        payload,
        "selective_repeat",
        window_size=4,
        chunk_size=200,
        ack_timeout_ms=500,
    )
    snapshot = result["snapshot"]
    assert snapshot["status"] == "completed"
    assert snapshot["integrity"] == "verified"
    assert snapshot["retransmissions"] == 0
    assert snapshot["average_rtt_ms"] is not None
    assert result["output"].read_bytes() == payload
    events = result["metrics"].events.list()
    first_ack = next(index for index, event in enumerate(events) if event["kind"] in {"ack", "sack"})
    sends = [event for event in events[:first_ack] if event["kind"] == "send"]
    assert len(sends) >= 4


def test_retransmits_only_the_missing_packet(tmp_path):
    dropped = {"done": False}

    def drop_seq_two(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        if packet and packet.packet_type == PacketType.DATA and packet.seq == 2 and not dropped["done"]:
            dropped["done"] = True
            return True
        return False

    payload = b"S" * 600
    result = run_transfer(
        tmp_path,
        payload,
        "selective_repeat",
        window_size=4,
        chunk_size=100,
        ack_timeout_ms=500,
        max_retries=6,
        sender_simulator=NetworkSimulator(drop_predicate=drop_seq_two),
    )
    snapshot = result["snapshot"]
    assert snapshot["status"] == "completed"
    assert result["output"].read_bytes() == payload
    assert set(snapshot["retransmitted_sequences"]) == {2}


def test_receiver_accepts_out_of_order_packets_inside_the_window(tmp_path):
    chunks = [bytes([index]) * 64 for index in range(5)]
    payload = b"".join(chunks)
    digest = sha256_bytes(payload)
    meta = FileMetadata.from_dict(
        {
            "filename": "sr.bin",
            "file_size": len(payload),
            "chunk_size": 64,
            "total_chunks": 5,
            "protocol": "selective_repeat",
            "window_size": 4,
            "sha256": digest,
        }
    )
    transfer_id = uuid.uuid4().bytes
    partial, final = output_paths(tmp_path, transfer_id.hex(), meta.filename)
    writer = FileReassembler(partial, final, meta, transfer_id.hex())
    sent = []
    session = SelectiveRepeatReceiver(meta, writer, lambda packet, addr, flag: sent.append(packet), transfer_id)
    addr = ("127.0.0.1", 9)

    def deliver(seq: int):
        session.handle(Packet(PacketType.DATA, transfer_id, seq=seq, payload=chunks[seq]), addr)

    deliver(1)
    deliver(3)
    assert writer.received == {1, 3}
    assert session.recv_base == 0
    assert all(packet.packet_type == PacketType.SACK for packet in sent)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=8, payload=b"z" * 64), addr)
    assert 8 not in writer.received
    deliver(1)
    assert writer.received == {1, 3}
    deliver(0)
    assert session.recv_base == 2
    deliver(2)
    assert session.recv_base == 4
    deliver(4)
    assert session.recv_base == 5
    assert writer.complete()
    session.handle(Packet(PacketType.FIN, transfer_id), addr)
    body = json.loads(sent[-1].payload)
    assert body["ok"] is True
    assert final.read_bytes() == payload


def _try_decode(datagram: bytes):
    try:
        return decode(datagram)
    except Exception:
        return None
