"""Minimal DueSoon FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException

from src.duesoon import __version__
from src.duesoon.config.settings import DueSoonSettings, get_settings
from src.duesoon.persistence.database import create_engine_from_settings, database_is_ready


def create_app(
    settings: DueSoonSettings | None = None,
    *,
    engine: Any | None = None,
) -> FastAPI:
    """Create an isolated DueSoon application."""

    runtime_settings = settings or get_settings()
    runtime_engine = engine or create_engine_from_settings(runtime_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        runtime_engine.dispose()

    application = FastAPI(
        title="DueSoon API",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.engine = runtime_engine

    @application.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "duesoon"}

    @application.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        if not database_is_ready(runtime_engine):
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ready", "database": "ready"}

    @application.get("/api/v1/system/info", tags=["system"])
    def system_info() -> dict[str, str | bool]:
        return {
            "service": "duesoon",
            "version": __version__,
            "environment": runtime_settings.environment,
            "dry_run": runtime_settings.dry_run,
            "scheduler_enabled": runtime_settings.scheduler_enabled,
            "notification_provider": "ntfy" if runtime_settings.ntfy_enabled else "disabled",
        }

    return application


app = create_app()
