from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.google import (
    GoogleCalendarEvidenceService,
    GoogleEvidenceService,
    GoogleWorkspaceSyncService,
)
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import CalendarBusyBlock, SchedulerState, SourceRecord


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


class GoogleClient:
    config = SimpleNamespace(gmail_enabled=True, calendar_enabled=True)

    def __init__(self) -> None:
        self.gmail_calls = 0
        self.calendar_calls = 0
        self.calendar_windows = []

    def list_gmail_messages(self, *, query: str, limit: int):
        self.gmail_calls += 1
        assert query == "label:inbox newer_than:90d"
        assert limit == 50
        return [{
            "id": "gmail-1",
            "from": "Professor <professor@example.edu>",
            "subject": "Midterm date",
            "body": "Midterm is Monday.",
        }]

    def list_calendar_events(self, *, start: datetime, end: datetime, limit: int = 250):
        self.calendar_calls += 1
        self.calendar_windows.append((start, end))
        return [{
            "id": "shift-1",
            "title": "Private work shift",
            "starts_at": (NOW + timedelta(hours=2)).isoformat(),
            "ends_at": (NOW + timedelta(hours=10)).isoformat(),
            "all_day": False,
            "status": "confirmed",
        }]


class Pipeline:
    def __init__(self) -> None:
        self.calls = 0

    def process_pending(self, *, limit: int):
        self.calls += 1
        assert limit == 10
        return SimpleNamespace(to_dict=lambda: {"processed_sources": 1})


class FailingPipeline:
    def __init__(self) -> None:
        self.calls = 0

    def process_pending(self, *, limit: int):
        self.calls += 1
        raise RuntimeError("provider rate limited")


def database(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'google-auto.db').as_posix()}",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    return engine, session_factory(engine)


def test_google_sync_runs_read_only_sources_and_persists_watermark(tmp_path: Path) -> None:
    engine, sessions = database(tmp_path)
    client = GoogleClient()
    pipeline = Pipeline()
    service = GoogleWorkspaceSyncService(
        sessions,
        client,
        GoogleEvidenceService(sessions),
        GoogleCalendarEvidenceService(sessions),
        pipeline,
        should_extract=lambda: True,
        interval_seconds=900,
        clock=lambda: NOW,
    )
    try:
        first = service.run_once()
        second = service.run_once()

        assert first["status"] == "synced"
        assert first["gmail"] == {"stored": 1, "unchanged": 0}
        assert first["calendar"]["stored"] == 1
        assert second["status"] == "skipped_interval"
        assert client.gmail_calls == client.calendar_calls == pipeline.calls == 1
        assert client.calendar_windows == [
            (NOW - timedelta(days=1), NOW + timedelta(days=60))
        ]
        with sessions() as session:
            assert session.scalar(select(SourceRecord.id)) is not None
            block = session.scalar(select(CalendarBusyBlock))
            assert block is not None and block.active is True
            assert session.get(SchedulerState, "google_workspace_sync").last_successful_at
    finally:
        engine.dispose()


def test_calendar_window_reconciliation_deactivates_removed_events(tmp_path: Path) -> None:
    engine, sessions = database(tmp_path)
    service = GoogleCalendarEvidenceService(sessions)
    event = {
        "id": "removed-shift",
        "starts_at": (NOW + timedelta(hours=2)).isoformat(),
        "ends_at": (NOW + timedelta(hours=8)).isoformat(),
        "all_day": False,
        "status": "confirmed",
    }
    try:
        service.store_events(
            [event], observed_at=NOW, window_start=NOW, window_end=NOW + timedelta(days=1)
        )
        result = service.store_events(
            [],
            observed_at=NOW + timedelta(minutes=15),
            window_start=NOW,
            window_end=NOW + timedelta(days=1),
        )

        with sessions() as session:
            block = session.scalar(select(CalendarBusyBlock))
            assert block is not None and block.active is False
        assert result["deactivated"] == 1
    finally:
        engine.dispose()


def test_extraction_failure_uses_backoff_without_blocking_source_refresh(
    tmp_path: Path,
) -> None:
    engine, sessions = database(tmp_path)
    current = [NOW]
    client = GoogleClient()
    pipeline = FailingPipeline()
    service = GoogleWorkspaceSyncService(
        sessions,
        client,
        GoogleEvidenceService(sessions),
        GoogleCalendarEvidenceService(sessions),
        pipeline,
        should_extract=lambda: True,
        interval_seconds=900,
        extraction_retry_seconds=3600,
        clock=lambda: current[0],
    )
    try:
        first = service.run_once()
        current[0] += timedelta(seconds=901)
        second = service.run_once()
        current[0] += timedelta(seconds=2700)
        third = service.run_once()

        assert first["extraction"] == {"status": "failed_backoff"}
        assert second["extraction"] == {"status": "skipped_backoff"}
        assert third["extraction"] == {"status": "failed_backoff"}
        assert pipeline.calls == 2
        assert client.gmail_calls == client.calendar_calls == 3
    finally:
        engine.dispose()
