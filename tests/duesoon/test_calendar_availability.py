from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.duesoon.api.app import create_app
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.google.availability import GoogleCalendarEvidenceService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import CalendarBusyBlock


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def service(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'availability.db').as_posix()}",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    return engine, GoogleCalendarEvidenceService(session_factory(engine))


def test_calendar_events_become_private_busy_blocks_and_update_idempotently(
    tmp_path: Path,
) -> None:
    engine, availability = service(tmp_path)
    try:
        first = availability.store_events(
            [
                {
                    "id": "secret-google-id",
                    "title": "Work at private employer",
                    "starts_at": "2026-08-30T09:00:00-04:00",
                    "ends_at": "2026-08-30T17:00:00-04:00",
                    "all_day": False,
                    "status": "confirmed",
                },
                {
                    "id": "cancelled",
                    "title": "Cancelled shift",
                    "starts_at": "2026-08-31T09:00:00-04:00",
                    "ends_at": "2026-08-31T17:00:00-04:00",
                    "status": "cancelled",
                },
            ],
            observed_at=NOW,
        )
        second = availability.store_events(
            [
                {
                    "id": "secret-google-id",
                    "title": "Changed private title",
                    "starts_at": "2026-08-30T10:00:00-04:00",
                    "ends_at": "2026-08-30T18:00:00-04:00",
                    "all_day": False,
                    "status": "confirmed",
                }
            ],
            observed_at=NOW + timedelta(hours=1),
        )

        assert first == {"stored": 1, "updated": 0, "ignored": 1}
        assert second == {"stored": 0, "updated": 1, "ignored": 0}
        with availability.sessions() as session:
            rows = session.scalars(select(CalendarBusyBlock)).all()
            assert len(rows) == 1
            assert rows[0].external_id_hash != "secret-google-id"
            assert rows[0].starts_at.replace(tzinfo=UTC) == datetime(
                2026, 8, 30, 14, tzinfo=UTC
            )
            rendered = repr(rows[0].__dict__)
            assert "private employer" not in rendered
            assert "Changed private title" not in rendered
    finally:
        engine.dispose()


def test_availability_summary_exposes_shift_load_without_inventing_capacity(
    tmp_path: Path,
) -> None:
    engine, availability = service(tmp_path)
    try:
        availability.store_events(
            [
                {
                    "id": "shift-1",
                    "title": "Work",
                    "starts_at": "2026-08-30T09:00:00+00:00",
                    "ends_at": "2026-08-30T17:00:00+00:00",
                    "all_day": False,
                    "status": "confirmed",
                }
            ],
            observed_at=NOW,
        )

        summary = availability.summary(
            start=datetime(2026, 8, 30, tzinfo=UTC),
            end=datetime(2026, 9, 1, tzinfo=UTC),
        )

        assert summary["blocked_minutes"] == 480
        assert summary["days_with_blocks"] == 1
        assert summary["days_without_blocks"] == 1
        assert summary["usable_capacity_minutes"] is None
        assert summary["confidence"] == "low"
    finally:
        engine.dispose()


class FakeCalendar:
    config = SimpleNamespace(gmail_enabled=False, calendar_enabled=True)

    def list_calendar_events(self, *, start, end):
        return [
            {
                "id": "work-shift",
                "title": "Private workplace",
                "starts_at": "2026-08-30T09:00:00+00:00",
                "ends_at": "2026-08-30T17:00:00+00:00",
                "all_day": False,
                "status": "confirmed",
                "html_url": None,
            }
        ]


def test_calendar_dashboard_persists_busy_intervals_and_returns_availability(
    tmp_path: Path,
) -> None:
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'calendar-api.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    app = create_app(settings, engine=engine, google_client=FakeCalendar())
    with TestClient(app, base_url="https://due.test") as client:
        client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://due.test"},
            json={"username": "owner", "password": "correct-password-123"},
        )
        response = client.get(
            "/api/v1/dashboard/calendar?start=2026-08-30&end=2026-08-31"
        )

    assert response.status_code == 200
    assert response.json()["availability"]["blocked_minutes"] == 480
    assert response.json()["availability"]["usable_capacity_minutes"] is None
    with session_factory(engine)() as session:
        assert len(session.scalars(select(CalendarBusyBlock)).all()) == 1
    engine.dispose()
