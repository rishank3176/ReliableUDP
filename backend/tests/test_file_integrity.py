import uuid

from app.file_manager import (
    FileMetadata,
    FileReassembler,
    expected_chunk_length,
    output_paths,
    sanitize_filename,
    sha256_bytes,
    sha256_file,
    total_chunks_for,
)
from app.packet import Packet, PacketType
from app.protocols.selective_repeat import SelectiveRepeatReceiver
from app.protocols.stop_and_wait import StopAndWaitReceiver


def test_sanitize_rejects_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..") == "upload.bin"
    assert sanitize_filename("") == "upload.bin"
    assert "/" not in sanitize_filename("a/b/c.txt")


def test_empty_and_multichunk_counts():
    assert total_chunks_for(0, 1024) == 0
    assert total_chunks_for(1024, 1024) == 1
    assert total_chunks_for(1025, 1024) == 2
    assert expected_chunk_length(1025, 1024, 0, 2) == 1024
    assert expected_chunk_length(1025, 1024, 1, 2) == 1


def test_reassembler_matches_bytes_and_hash(tmp_path):
    payload = bytes([index % 256 for index in range(2500)])
    digest = sha256_bytes(payload)
    meta = FileMetadata.from_dict(
        {
            "filename": "blob.bin",
            "file_size": len(payload),
            "chunk_size": 1000,
            "total_chunks": 3,
            "protocol": "selective_repeat",
            "window_size": 4,
            "sha256": digest,
        }
    )
    partial, final = output_paths(tmp_path, "abc", meta.filename)
    writer = FileReassembler(partial, final, meta, "abc")
    for seq in (2, 0, 1):
        start = seq * 1000
        writer.write_chunk(seq, payload[start : start + expected_chunk_length(len(payload), 1000, seq, 3)])
    assert writer.write_chunk(0, payload[:1000]) is False
    assert writer.complete()
    ok, found, size = writer.verify()
    assert ok
    assert found == digest
    assert size == len(payload)
    path = writer.finalize(found)
    assert sha256_file(path) == digest
    assert path.read_bytes() == payload
    assert path.parent == tmp_path


def test_empty_file_hash_and_reassembly(tmp_path):
    digest = sha256_bytes(b"")
    assert digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    meta = FileMetadata.from_dict(
        {
            "filename": "empty.txt",
            "file_size": 0,
            "chunk_size": 128,
            "total_chunks": 0,
            "protocol": "stop_and_wait",
            "window_size": 1,
            "sha256": digest,
        }
    )
    partial, final = output_paths(tmp_path, "empty", "empty.txt")
    writer = FileReassembler(partial, final, meta, "empty")
    assert writer.complete()
    ok, found, size = writer.verify()
    assert ok and found == digest and size == 0
    assert writer.finalize(found).read_bytes() == b""


def test_receiver_rejects_corrupted_reconstruction(tmp_path):
    payload = b"reliable-udp-file"
    digest = sha256_bytes(payload)
    meta = FileMetadata.from_dict(
        {
            "filename": "note.txt",
            "file_size": len(payload),
            "chunk_size": 64,
            "total_chunks": 1,
            "protocol": "stop_and_wait",
            "window_size": 1,
            "sha256": digest,
        }
    )
    transfer_id = uuid.uuid4().bytes
    partial, final = output_paths(tmp_path, transfer_id.hex(), meta.filename)
    writer = FileReassembler(partial, final, meta, transfer_id.hex())
    sent = []

    def send_fn(packet, addr, retransmit):
        sent.append(packet)

    session = StopAndWaitReceiver(meta, writer, send_fn, transfer_id)
    session.handle(Packet(PacketType.DATA, transfer_id, seq=0, payload=payload), ("127.0.0.1", 1))
    writer._handle.seek(0)
    writer._handle.write(b"X")
    writer._handle.flush()
    session.handle(Packet(PacketType.FIN, transfer_id, payload=b"{}"), ("127.0.0.1", 1))
    fin = sent[-1]
    assert fin.packet_type == PacketType.FIN_ACK
    assert b'"ok":false' in fin.payload
    assert not final.exists()


def test_metadata_rejects_bad_window_for_stop_and_wait():
    import pytest

    with pytest.raises(ValueError, match="window"):
        FileMetadata.from_dict(
            {
                "filename": "a.txt",
                "file_size": 1,
                "chunk_size": 64,
                "total_chunks": 1,
                "protocol": "stop_and_wait",
                "window_size": 4,
                "sha256": sha256_bytes(b"a"),
            }
        )


def test_selective_receiver_does_not_need_the_hash_helper(tmp_path):
    # Imported so a missing receiver class fails this module too.
    assert SelectiveRepeatReceiver is not None
