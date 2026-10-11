"""API and transfer configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WINDOW_SIZE,
    MAX_CHUNK_SIZE,
    MAX_DELAY_MS,
    MAX_LOSS_PERCENT,
    MAX_RETRIES,
    MAX_TIMEOUT_MS,
    MAX_WINDOW_SIZE,
    MIN_CHUNK_SIZE,
    MIN_RETRIES,
    MIN_TIMEOUT_MS,
    MIN_WINDOW_SIZE,
    PROTOCOL_GO_BACK_N,
    PROTOCOLS,
)


class TransferParams(BaseModel):
    protocol: str = PROTOCOL_GO_BACK_N
    window_size: int = Field(DEFAULT_WINDOW_SIZE, ge=MIN_WINDOW_SIZE, le=MAX_WINDOW_SIZE)
    chunk_size: int = Field(DEFAULT_CHUNK_SIZE, ge=MIN_CHUNK_SIZE, le=MAX_CHUNK_SIZE)
    ack_timeout_ms: int = Field(DEFAULT_TIMEOUT_MS, ge=MIN_TIMEOUT_MS, le=MAX_TIMEOUT_MS)
    max_retries: int = Field(DEFAULT_RETRIES, ge=MIN_RETRIES, le=MAX_RETRIES)
    receiver_host: str = "127.0.0.1"
    receiver_port: int = Field(9000, ge=1, le=65535)
    loss_percent: float = Field(0, ge=0, le=MAX_LOSS_PERCENT)
    delay_ms: float = Field(0, ge=0, le=MAX_DELAY_MS)
    corruption_percent: float = Field(0, ge=0, le=MAX_LOSS_PERCENT)
    seed: int | None = None

    @field_validator("protocol")
    @classmethod
    def known_protocol(cls, value: str) -> str:
        if value not in PROTOCOLS:
            raise ValueError(f"protocol must be one of: {', '.join(PROTOCOLS)}")
        return value

    @field_validator("receiver_host")
    @classmethod
    def host_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(char.isspace() for char in cleaned) or len(cleaned) > 253:
            raise ValueError("receiver host is invalid")
        return cleaned


class BenchmarkParams(TransferParams):
    generate_bytes: int = Field(32768, ge=0, le=2_000_000)
