"""FastAPI entry point for the ReliableUDP dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import Settings
from .transfer_manager import TransferManager


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    manager = TransferManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.start_receiver()
        yield
        manager.stop_receiver()

    app = FastAPI(title="ReliableUDP", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
