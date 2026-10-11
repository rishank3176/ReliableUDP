"""File segmentation, safe names, hashing, and reconstruction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import (
    MAX_CHUNK_SIZE,
    MAX_WINDOW_SIZE,
    MIN_CHUNK_SIZE,
    MIN_WINDOW_SIZE,
    PROTOCOLS,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sanitize_filename(name: str | None) -> str:
    """Reduce a user-supplied name to a single safe path component."""
    raw = "upload.bin" if not name else str(name).replace("\x00", "")
    base = Path(raw).name
    base = base.replace("\\", "_").replace("/", "_").strip()
    if base in {"", ".", ".."}:
        return "upload.bin"
    cleaned = base.lstrip(".")
    allowed: list[str] = []
    for char in cleaned:
        if char.isalnum() or char in "._- ":
            allowed.append(char)
        else:
            allowed.append("_")
    result = "".join(allowed).strip().strip(".")
    if not result:
        return "upload.bin"
    return result[:180]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def total_chunks_for(file_size: int, chunk_size: int) -> int:
    if file_size < 0:
        raise ValueError("file size cannot be negative")
    if file_size == 0:
        return 0
    if chunk_size <= 0:
        raise ValueError("chunk size must be positive")
    return math.ceil(file_size / chunk_size)


def expected_chunk_length(file_size: int, chunk_size: int, seq: int, total_chunks: int) -> int:
    if total_chunks == 0:
        raise ValueError("empty file has no chunks")
    if seq < 0 or seq >= total_chunks:
        raise ValueError("sequence out of range")
    if seq < total_chunks - 1:
        return chunk_size
    return file_size - (chunk_size * (total_chunks - 1))


@dataclass
class FileMetadata:
    filename: str
    file_size: int
    chunk_size: int
    total_chunks: int
    protocol: str
    window_size: int
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_payload(self) -> bytes:
        return json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_payload(cls, payload: bytes) -> FileMetadata:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("START metadata is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("START metadata must be an object")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> FileMetadata:
        try:
            filename = sanitize_filename(str(data["filename"]))
            file_size = int(data["file_size"])
            chunk_size = int(data["chunk_size"])
            total_chunks = int(data["total_chunks"])
            protocol = str(data["protocol"])
            window_size = int(data["window_size"])
            digest = str(data["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("START metadata is missing a required field") from exc
        if protocol not in PROTOCOLS:
            raise ValueError("unsupported reliability protocol")
        if file_size < 0:
            raise ValueError("file size cannot be negative")
        if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("chunk size is outside the supported range")
        if total_chunks != total_chunks_for(file_size, chunk_size):
            raise ValueError("chunk count does not match the file size")
        if not MIN_WINDOW_SIZE <= window_size <= MAX_WINDOW_SIZE:
            raise ValueError("window size is outside the supported range")
        if protocol == "stop_and_wait" and window_size != 1:
            raise ValueError("Stop and Wait requires a window size of 1")
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("SHA256 must be 64 hexadecimal characters")
        return cls(
            filename=filename,
            file_size=file_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            protocol=protocol,
            window_size=window_size,
            sha256=digest,
        )


def output_paths(output_dir: Path, transfer_hex: str, filename: str) -> tuple[Path, Path]:
    safe = sanitize_filename(filename)
    final = output_dir / f"{transfer_hex}_{safe}"
    partial = output_dir / f".{transfer_hex}_{safe}.partial"
    return partial, final


class ChunkSource:
    """Random-access reader for fixed-size file chunks."""

    def __init__(self, path: Path, chunk_size: int, file_size: int) -> None:
        self.path = path
        self.chunk_size = chunk_size
        self.file_size = file_size
        self.total_chunks = total_chunks_for(file_size, chunk_size)
        self._handle = path.open("rb")

    def get(self, seq: int) -> bytes:
        expected = expected_chunk_length(self.file_size, self.chunk_size, seq, self.total_chunks)
        self._handle.seek(seq * self.chunk_size)
        data = self._handle.read(expected)
        if len(data) != expected:
            raise OSError(f"short read for chunk {seq}")
        return data

    def close(self) -> None:
        self._handle.close()


class FileReassembler:
    """Disk-backed reconstruction. Chunk ``n`` is written at ``n * chunk_size``."""

    def __init__(self, partial: Path, final: Path, meta: FileMetadata, transfer_id: str) -> None:
        self.partial = partial
        self.final = final
        self.meta = meta
        self.transfer_id = transfer_id
        self.received: set[int] = set()
        partial.parent.mkdir(parents=True, exist_ok=True)
        self._handle = partial.open("wb+")
        if meta.file_size == 0:
            self._handle.truncate(0)

    def write_chunk(self, seq: int, data: bytes) -> bool:
        if seq in self.received:
            return False
        expected = expected_chunk_length(
            self.meta.file_size, self.meta.chunk_size, seq, self.meta.total_chunks
        )
        if len(data) != expected:
            raise ValueError("chunk length does not match metadata")
        if self._handle is None:
            raise OSError("reassembler is closed")
        self._handle.seek(seq * self.meta.chunk_size)
        self._handle.write(data)
        self.received.add(seq)
        return True

    def complete(self) -> bool:
        return len(self.received) == self.meta.total_chunks

    def verify(self) -> tuple[bool, str, int]:
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._handle = None
        digest = sha256_file(self.partial)
        size = self.partial.stat().st_size
        ok = self.complete() and digest == self.meta.sha256 and size == self.meta.file_size
        return ok, digest, size

    def finalize(self, digest: str) -> Path:
        os.replace(self.partial, self.final)
        meta_path = self.final.with_name(self.final.name + ".meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "transfer_id": self.transfer_id,
                    "filename": self.meta.filename,
                    "file_size": self.meta.file_size,
                    "sha256": digest,
                    "protocol": self.meta.protocol,
                    "verified": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return self.final

    def abort(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None
        if self.partial.exists():
            self.partial.unlink()
        if self.final.exists() and not self.complete():
            self.final.unlink()
