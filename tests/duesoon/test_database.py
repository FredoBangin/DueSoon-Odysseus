from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import text

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence import database


def test_engine_creates_sqlite_parent_and_enables_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "duesoon.db"
    settings = DueSoonSettings(
        _env_file=None,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    engine = database.create_engine_from_settings(settings)
    try:
        with engine.connect() as connection:
            enabled = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
            journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
            busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
    finally:
        engine.dispose()

    assert database_path.parent.is_dir()
    assert enabled == 1
    assert journal_mode == "wal"
    assert busy_timeout >= 10_000


def test_database_readiness_executes_query() -> None:
    settings = DueSoonSettings(_env_file=None, database_url="sqlite:///:memory:")
    engine = database.create_engine_from_settings(settings)
    try:
        assert database.database_is_ready(engine) is True
    finally:
        engine.dispose()


def test_database_readiness_returns_false_on_connection_error() -> None:
    class BrokenEngine:
        def connect(self):
            raise OSError("database unavailable")

    assert database.database_is_ready(BrokenEngine()) is False


def test_new_persistence_layer_does_not_import_legacy_database() -> None:
    source = inspect.getsource(database)
    assert "core.database" not in source
