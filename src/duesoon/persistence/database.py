"""SQLAlchemy engine lifecycle for DueSoon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.config.settings import DueSoonSettings


def _prepare_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine_from_settings(settings: DueSoonSettings) -> Engine:
    """Create an engine without creating application tables at import time."""

    _prepare_sqlite_parent(settings.database_url)
    is_sqlite = settings.database_url.startswith("sqlite")
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True,
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def database_is_ready(engine: Any) -> bool:
    """Return whether the database accepts a minimal query."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def create_schema(engine: Engine) -> None:
    """Create prototype tables explicitly during application startup."""

    from src.duesoon.persistence.models import Base

    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create short-lived SQLAlchemy sessions bound to one engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
