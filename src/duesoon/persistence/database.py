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
        connect_args={"check_same_thread": False, "timeout": 30.0} if is_sqlite else {},
        pool_pre_ping=True,
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=10000")
                if engine.url.database != ":memory:":
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
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
    """Create tables and apply forward-only compatibility migrations."""

    from src.duesoon.persistence.models import Base

    Base.metadata.create_all(engine)
    _apply_schema_migrations(engine)


def _apply_schema_migrations(engine: Engine) -> None:
    """Upgrade the supported SQLite schema without rebuilding user data."""

    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        if 1 not in applied:
            columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(reminder_events)"))
            }
            if "reminder_kind" not in columns:
                connection.execute(text(
                    "ALTER TABLE reminder_events ADD COLUMN reminder_kind "
                    "VARCHAR(30) NOT NULL DEFAULT 'standard'"
                ))
            if "interval_key" not in columns:
                connection.execute(text(
                    "ALTER TABLE reminder_events ADD COLUMN interval_key VARCHAR(50)"
                ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_reminder_adaptive_interval "
                "ON reminder_events (assignment_id, deadline_at, reminder_kind, interval_key) "
                "WHERE reminder_kind = 'adaptive'"
            ))
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (1)")
            )
        if 2 not in applied:
            columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(assistant_exchanges)"))
            }
            if "decision_trace" not in columns:
                connection.execute(text(
                    "ALTER TABLE assistant_exchanges ADD COLUMN decision_trace "
                    "JSON NOT NULL DEFAULT '{}'"
                ))
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (2)")
            )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create short-lived SQLAlchemy sessions bound to one engine."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
