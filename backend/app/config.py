"""Runtime limits and environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROTOCOL_STOP_AND_WAIT = "stop_and_wait"
PROTOCOL_GO_BACK_N = "go_back_n"
PROTOCOL_SELECTIVE_REPEAT = "selective_repeat"
PROTOCOLS = (
    PROTOCOL_STOP_AND_WAIT,
    PROTOCOL_GO_BACK_N,
    PROTOCOL_SELECTIVE_REPEAT,
)

PROTOCOL_LABELS = {
    PROTOCOL_STOP_AND_WAIT: "Stop and Wait",
    PROTOCOL_GO_BACK_N: "Go Back N",
    PROTOCOL_SELECTIVE_REPEAT: "Selective Repeat",
}

MIN_CHUNK_SIZE = 64
MAX_CHUNK_SIZE = 1400
DEFAULT_CHUNK_SIZE = 1024

MIN_WINDOW_SIZE = 1
MAX_WINDOW_SIZE = 32
DEFAULT_WINDOW_SIZE = 8

MIN_TIMEOUT_MS = 20
MAX_TIMEOUT_MS = 30_000
DEFAULT_TIMEOUT_MS = 500

MIN_RETRIES = 0
MAX_RETRIES = 30
DEFAULT_RETRIES = 8

MAX_DELAY_MS = 10_000
MAX_LOSS_PERCENT = 100.0
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass
class Settings:
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    udp_host: str = "127.0.0.1"
    udp_port: int = 9000
    upload_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "uploads")
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "received_files")
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    local_receiver: bool = True
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Settings:
        origins = os.environ.get("RELIABLEUDP_CORS_ORIGINS")
        settings = cls(
            api_host=os.environ.get("RELIABLEUDP_API_HOST", "127.0.0.1"),
            api_port=_env_int("RELIABLEUDP_API_PORT", 8000),
            udp_host=os.environ.get("RELIABLEUDP_HOST", "127.0.0.1"),
            udp_port=_env_int("RELIABLEUDP_PORT", 9000),
            upload_dir=Path(
                os.environ.get("RELIABLEUDP_UPLOAD_DIR", str(PROJECT_ROOT / "uploads"))
            ).expanduser(),
            output_dir=Path(
                os.environ.get("RELIABLEUDP_OUTPUT_DIR", str(PROJECT_ROOT / "received_files"))
            ).expanduser(),
            max_upload_bytes=_env_int("RELIABLEUDP_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
            local_receiver=_env_bool("RELIABLEUDP_LOCAL_RECEIVER", True),
        )
        if origins:
            settings.cors_origins = [item.strip() for item in origins.split(",") if item.strip()]
        if not settings.upload_dir.is_absolute():
            settings.upload_dir = PROJECT_ROOT / settings.upload_dir
        if not settings.output_dir.is_absolute():
            settings.output_dir = PROJECT_ROOT / settings.output_dir
        settings.ensure_directories()
        return settings


def public_config(settings: Settings) -> dict:
    return {
        "protocols": [
            {"id": protocol, "label": PROTOCOL_LABELS[protocol]} for protocol in PROTOCOLS
        ],
        "defaults": {
            "protocol": PROTOCOL_GO_BACK_N,
            "window_size": DEFAULT_WINDOW_SIZE,
            "chunk_size": DEFAULT_CHUNK_SIZE,
            "ack_timeout_ms": DEFAULT_TIMEOUT_MS,
            "max_retries": DEFAULT_RETRIES,
            "receiver_host": settings.udp_host if settings.udp_host != "0.0.0.0" else "127.0.0.1",
            "receiver_port": settings.udp_port,
            "loss_percent": 0,
            "delay_ms": 0,
            "corruption_percent": 0,
        },
        "limits": {
            "chunk_size": {"min": MIN_CHUNK_SIZE, "max": MAX_CHUNK_SIZE},
            "window_size": {"min": MIN_WINDOW_SIZE, "max": MAX_WINDOW_SIZE},
            "ack_timeout_ms": {"min": MIN_TIMEOUT_MS, "max": MAX_TIMEOUT_MS},
            "max_retries": {"min": MIN_RETRIES, "max": MAX_RETRIES},
            "delay_ms": {"min": 0, "max": MAX_DELAY_MS},
            "loss_percent": {"min": 0, "max": MAX_LOSS_PERCENT},
            "corruption_percent": {"min": 0, "max": MAX_LOSS_PERCENT},
            "max_upload_bytes": settings.max_upload_bytes,
        },
        "local_receiver_enabled": settings.local_receiver,
        "notes": {
            "stop_and_wait_window": "Stop and Wait always uses an effective window of 1.",
            "ack_timeout": (
                "The acknowledgement timer starts after the sender hands a datagram to UDP. "
                "Sender-side artificial delay does not consume that timer. Receiver-side delay does. "
                "Set the timeout above the configured delay (a practical minimum is delay + 150 ms)."
            ),
            "simulation_scope": (
                "The built-in receiver applies loss, delay, and corruption to its outgoing "
                "acknowledgements and control replies. The sender applies them to data and "
                "control datagrams it transmits. A remote receiver only sees this behaviour "
                "when it is started with the same simulation options."
            ),
        },
    }
