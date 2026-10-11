import uuid

from app.file_manager import FileMetadata, FileReassembler, output_paths, sha256_bytes
from app.network_simulator import NetworkSimulator
from app.packet import Packet, PacketType, decode
from app.protocols.go_back_n import GoBackNReceiver

from helpers import run_transfer


def test_window_sends_multiple_packets_before_an_ack(tmp_path):
    payload = bytes(range(256)) * 4
    result = run_transfer(
        tmp_path,
        payload,
        "go_back_n",
        window_size=4,
        chunk_size=128,
        ack_timeout_ms=500,
    )
    snapshot = result["snapshot"]
    assert snapshot["status"] == "completed"
    assert snapshot["integrity"] == "verified"
    assert snapshot["window_size"] == 4
    assert snapshot["retransmissions"] == 0
    assert snapshot["average_rtt_ms"] is not None
    assert result["output"].read_bytes() == payload
    events = result["metrics"].events.list()
    first_ack = next(index for index, event in enumerate(events) if event["kind"] == "ack")
    sends = [event for event in events[:first_ack] if event["kind"] == "send"]
    assert len(sends) >= 4


def test_cumulative_ack_and_loss_retransmit_the_outstanding_window(tmp_path):
    dropped = {"done": False}

    def drop_seq_two(datagram: bytes) -> bool:
        packet = _try_decode(datagram)
        if packet and packet.packet_type == PacketType.DATA and packet.seq == 2 and not dropped["done"]:
            dropped["done"] = True
            return True
        return False

    payload = b"G" * 600
    result = run_transfer(
        tmp_path,
        payload,
        "go_back_n",
        window_size=4,
        chunk_size=100,
        ack_timeout_ms=250,
        max_retries=6,
        sender_simulator=NetworkSimulator(drop_predicate=drop_seq_two),
    )
    snapshot = result["snapshot"]
    assert snapshot["status"] == "completed"
    assert result["output"].read_bytes() == payload
    retransmitted = set(snapshot["retransmitted_sequences"])
    assert 2 in retransmitted
    assert any(seq > 2 for seq in retransmitted)


def test_receiver_discards_out_of_order_and_duplicate_data(tmp_path):
    chunks = [b"a" * 64, b"b" * 64, b"c" * 64]
    payload = b"".join(chunks)
    digest = sha256_bytes(payload)
    meta = FileMetadata.from_dict(
        {
            "filename": "gbn.bin",
            "file_size": len(payload),
            "chunk_size": 64,
            "total_chunks": 3,
            "protocol": "go_back_n",
            "window_size": 3,
            "sha256": digest,
        }
    )
    transfer_id = uuid.uuid4().bytes
    partial, final = output_paths(tmp_path, transfer_id.hex(), meta.filename)
    writer = FileReassembler(partial, final, meta, transfer_id.hex())
    sent = []
    session = GoBackNReceiver(meta, writer, lambda packet, addr, flag: sent.append(packet), transfer_id)
    addr = ("127.0.0.1", 9)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=1, payload=chunks[1]), addr)
    assert writer.received == set()
    assert sent[-1].packet_type == PacketType.ACK
    assert sent[-1].ack == 0
    session.handle(Packet(PacketType.DATA, transfer_id, seq=0, payload=chunks[0]), addr)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=0, payload=chunks[0]), addr)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=1, payload=chunks[1]), addr)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=2, payload=chunks[2]), addr)
    assert writer.received == {0, 1, 2}
    assert sent[-1].ack == 3
    assert writer._handle is not None
    writer._handle.seek(0)
    assert writer._handle.read() == payload


def _try_decode(datagram: bytes):
    try:
        return decode(datagram)
    except Exception:
        return None
