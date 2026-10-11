"""Dashboard REST API. HTTP carries control and files; file bytes move over UDP."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from . import __version__
from .config import public_config
from .file_manager import sanitize_filename
from .models import BenchmarkParams, TransferParams
from .transfer_manager import TransferBusy, public_benchmark, public_transfer

router = APIRouter(prefix="/api")


def _manager(request: Request):
    return request.app.state.manager


def _settings(request: Request):
    return request.app.state.settings


@router.get("/health")
def health(request: Request) -> dict:
    receiver = _manager(request).receiver_status()
    return {
        "status": "ok" if receiver.get("error") is None else "degraded",
        "api": "ok",
        "version": __version__,
        "udp_receiver": receiver,
    }


@router.get("/config")
def config(request: Request) -> dict:
    return public_config(_settings(request))


@router.post("/transfers", status_code=201)
async def create_transfer(
    request: Request,
    file: UploadFile = File(...),
    protocol: str = Form("go_back_n"),
    window_size: int = Form(8),
    chunk_size: int = Form(1024),
    ack_timeout_ms: int = Form(500),
    max_retries: int = Form(8),
    receiver_host: str = Form("127.0.0.1"),
    receiver_port: int = Form(9000),
    loss_percent: float = Form(0),
    delay_ms: float = Form(0),
    corruption_percent: float = Form(0),
    seed: str = Form(""),
) -> dict:
    params = _params_from_form(
        protocol,
        window_size,
        chunk_size,
        ack_timeout_ms,
        max_retries,
        receiver_host,
        receiver_port,
        loss_percent,
        delay_ms,
        corruption_percent,
        seed,
    )
    destination, filename = await _save_upload(file, _settings(request))
    try:
        record = _manager(request).create_transfer(destination, filename, params)
    except TransferBusy as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return public_transfer(record)


@router.get("/transfers")
def list_transfers(request: Request) -> dict:
    return {"transfers": [public_transfer(item) for item in _manager(request).list_transfers()]}


@router.get("/transfers/{transfer_id}")
def get_transfer(transfer_id: str, request: Request) -> dict:
    record = _manager(request).get(transfer_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return public_transfer(record)


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: str, request: Request) -> dict:
    try:
        record = _manager(request).cancel(transfer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    return public_transfer(record)


@router.get("/transfers/{transfer_id}/download")
def download_transfer(transfer_id: str, request: Request):
    record = _manager(request).get(transfer_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    snapshot = record.metrics.snapshot()
    if snapshot["status"] != "completed" or snapshot["integrity"] != "verified":
        raise HTTPException(status_code=409, detail="The reconstructed file is not verified")
    path = _safe_output(record.output_path, _settings(request).output_dir)
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Reconstructed file is not on this machine. A remote receiver keeps the file locally.",
        )
    return FileResponse(path, filename=record.filename, media_type="application/octet-stream")


@router.get("/received-files")
def received_files(request: Request) -> dict:
    directory = _settings(request).output_dir
    files = []
    if directory.exists():
        for path in sorted(directory.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file() or path.name.startswith(".") or path.name.endswith(".meta.json"):
                continue
            resolved = _safe_output(path, directory)
            if resolved is None:
                continue
            meta_path = path.with_name(path.name + ".meta.json")
            meta = {}
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
            files.append(
                {
                    "name": path.name,
                    "filename": meta.get("filename") or path.name,
                    "size": path.stat().st_size,
                    "sha256": meta.get("sha256"),
                    "protocol": meta.get("protocol"),
                    "transfer_id": meta.get("transfer_id"),
                    "verified": bool(meta.get("verified")),
                }
            )
    return {"files": files}


@router.post("/benchmark", status_code=202)
async def start_benchmark(
    request: Request,
    file: UploadFile | None = File(None),
    protocol: str = Form("go_back_n"),
    window_size: int = Form(8),
    chunk_size: int = Form(1024),
    ack_timeout_ms: int = Form(500),
    max_retries: int = Form(8),
    receiver_host: str = Form("127.0.0.1"),
    receiver_port: int = Form(9000),
    loss_percent: float = Form(0),
    delay_ms: float = Form(0),
    corruption_percent: float = Form(0),
    seed: str = Form(""),
    generate_bytes: int = Form(32768),
) -> dict:
    try:
        params = BenchmarkParams(
            protocol=protocol,
            window_size=window_size,
            chunk_size=chunk_size,
            ack_timeout_ms=ack_timeout_ms,
            max_retries=max_retries,
            receiver_host=receiver_host,
            receiver_port=receiver_port,
            loss_percent=loss_percent,
            delay_ms=delay_ms,
            corruption_percent=corruption_percent,
            seed=_optional_seed(seed),
            generate_bytes=generate_bytes,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc
    transfer_params = TransferParams(**params.model_dump(exclude={"generate_bytes"}))
    if file is not None and file.filename:
        destination, filename = await _save_upload(file, _settings(request))
    else:
        filename = "benchmark.bin"
        destination = _settings(request).upload_dir / f"benchmark-{generate_bytes}.bin"
        payload = _benchmark_payload(generate_bytes, params.seed)
        destination.write_bytes(payload)
    try:
        benchmark = _manager(request).start_benchmark(destination, filename, transfer_params)
    except TransferBusy as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return public_benchmark(benchmark)


@router.get("/benchmark")
def latest_benchmark(request: Request) -> dict:
    manager = _manager(request)
    if manager.latest_benchmark_id is None:
        return {"benchmark": None}
    benchmark = manager.benchmarks.get(manager.latest_benchmark_id)
    return {"benchmark": None if benchmark is None else public_benchmark(benchmark)}


@router.get("/benchmark/{benchmark_id}")
def get_benchmark(benchmark_id: str, request: Request) -> dict:
    benchmark = _manager(request).benchmarks.get(benchmark_id)
    if benchmark is None:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return public_benchmark(benchmark)


def _params_from_form(
    protocol,
    window_size,
    chunk_size,
    ack_timeout_ms,
    max_retries,
    receiver_host,
    receiver_port,
    loss_percent,
    delay_ms,
    corruption_percent,
    seed,
) -> TransferParams:
    try:
        return TransferParams(
            protocol=protocol,
            window_size=window_size,
            chunk_size=chunk_size,
            ack_timeout_ms=ack_timeout_ms,
            max_retries=max_retries,
            receiver_host=receiver_host,
            receiver_port=receiver_port,
            loss_percent=loss_percent,
            delay_ms=delay_ms,
            corruption_percent=corruption_percent,
            seed=_optional_seed(seed),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc


def _optional_seed(seed: str | int | None) -> int | None:
    if seed is None:
        return None
    text = str(seed).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Seed must be an integer") from exc


def _validation_detail(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []))
        messages.append(f"{loc}: {error.get('msg')}" if loc else error.get("msg", "invalid value"))
    return "; ".join(messages) or "Invalid configuration"


async def _save_upload(upload: UploadFile, settings) -> tuple[Path, str]:
    filename = sanitize_filename(upload.filename)
    destination = settings.upload_dir / f"incoming-{filename}"
    # A unique prefix is added by the caller path; include a random suffix via the file object name.
    destination = settings.upload_dir / f"{Path(destination).stem}-{id(upload)}-{filename}"
    total = 0
    try:
        with destination.open("wb") as handle:
            while True:
                block = await upload.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="File exceeds the upload limit")
                handle.write(block)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not store the upload") from exc
    return destination, filename


def _safe_output(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(root_resolved):
        return None
    return resolved


def _benchmark_payload(size: int, seed: int | None) -> bytes:
    import random

    rng = random.Random(0 if seed is None else seed)
    return rng.randbytes(size)
