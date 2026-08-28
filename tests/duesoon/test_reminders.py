from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from src.duesoon.reminders.checkpoints import CHECKPOINT_MINUTES, crossed_checkpoint
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import PublishResult
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import ReminderEvent, SchedulerState
from src.duesoon.reminders.service import ReminderService


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (timedelta(hours=24), 1440),
        (timedelta(hours=12), 720),
        (timedelta(hours=6), 360),
        (timedelta(hours=1), 60),
        (timedelta(minutes=15), 15),
        (timedelta(hours=5), 360),
        (timedelta(minutes=10), 15),
    ],
)
def test_first_evaluation_selects_nearest_crossed_checkpoint(
    remaining: timedelta,
    expected: int,
) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    assert crossed_checkpoint(now + remaining, None, now) == expected


def test_checkpoint_set_is_exact_product_contract() -> None:
    assert CHECKPOINT_MINUTES == (1440, 720, 360, 60, 15)


def test_downtime_catchup_selects_only_most_recent_crossed_checkpoint() -> None:
    due_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    previous = due_at - timedelta(hours=13)
    now = due_at - timedelta(hours=5)

    assert crossed_checkpoint(due_at, previous, now) == 360


def test_equal_previous_checkpoint_is_not_crossed_again() -> None:
    due_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    previous = due_at - timedelta(hours=6)
    now = due_at - timedelta(hours=5)

    assert crossed_checkpoint(due_at, previous, now) is None


@pytest.mark.parametrize(
    "due_at",
    [
        datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
        datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        datetime(2026, 8, 27, 11, 59, tzinfo=UTC),
    ],
)
def test_first_evaluation_ignores_outside_active_window(due_at: datetime) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    assert crossed_checkpoint(due_at, None, now) is None


class ReminderCanvasClient:
    def __init__(self, due_at: datetime, refresh_state: str = "unsubmitted") -> None:
        self.due_at = due_at
        self.refresh_state = refresh_state
        self.refresh_calls = 0

    def list_courses(self):
        return [
            {
                "id": 42,
                "name": "Network Security",
                "course_code": "CIS-420",
                "workflow_state": "available",
                "term": {"name": "Fall 2026"},
            }
        ]

    def list_assignments(self, course_id: str):
        assert course_id == "42"
        return [
            {
                "id": 99,
                "name": "Lab 1",
                "description": "Complete the lab",
                "due_at": self.due_at.isoformat().replace("+00:00", "Z"),
                "points_possible": 25,
                "submission_types": ["online_upload"],
                "grading_type": "points",
                "published": True,
                "workflow_state": "published",
                "updated_at": "2026-08-25T12:00:00Z",
                "submission": {
                    "id": 501,
                    "workflow_state": "unsubmitted",
                    "missing": False,
                    "late": False,
                },
            }
        ]

    def get_submission(self, course_id: str, assignment_id: str):
        assert course_id == "42"
        assert assignment_id == "99"
        self.refresh_calls += 1
        return {
            "id": 501,
            "workflow_state": self.refresh_state,
            "submitted_at": (
                "2026-08-27T12:01:00Z"
                if self.refresh_state == "submitted"
                else None
            ),
            "missing": False,
            "late": False,
        }


class ReminderPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(self, **payload: object) -> PublishResult:
        self.calls.append(payload)
        return PublishResult(provider_message_id="provider-reminder-1")


def build_reminder_service(
    tmp_path: Path,
    *,
    now_ref: list[datetime],
    due_at: datetime,
    refresh_state: str = "unsubmitted",
    dry_run: bool = False,
):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'reminders.db').as_posix()}",
        dry_run=dry_run,
        ntfy_enabled=not dry_run,
        ntfy_url="https://notify.example.test" if not dry_run else None,
        ntfy_topic="private-topic" if not dry_run else None,
        ntfy_token="ntfy-token" if not dry_run else None,
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    canvas = ReminderCanvasClient(due_at, refresh_state)
    sync = CanvasSyncService(canvas, sessions, clock=lambda: now_ref[0])
    publisher = ReminderPublisher()
    notifications = NotificationService(settings, sessions, publisher)
    service = ReminderService(
        sessions,
        sync,
        notifications,
        clock=lambda: now_ref[0],
    )
    return engine, sessions, canvas, publisher, service


def test_incomplete_assignment_sends_once_after_immediate_recheck(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    engine, sessions, canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(hours=5),
    )
    try:
        first = service.run_once()
        second = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            state = session.get(SchedulerState, "canvas_reminders")
            assert event is not None
            assert event.checkpoint_minutes == 360
            assert event.status == "sent"
            assert event.submission_recheck_status == "not_submitted"
            assert state is not None and state.last_successful_at is not None
        assert first.sent == 1
        assert second.sent == 0
        assert canvas.refresh_calls == 1
        assert len(publisher.calls) == 1
    finally:
        engine.dispose()


def test_submitted_assignment_is_suppressed_after_immediate_recheck(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    engine, sessions, canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(hours=5),
        refresh_state="submitted",
    )
    try:
        summary = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            assert event is not None
            assert event.status == "suppressed_submission"
            assert event.submission_recheck_status == "submitted"
        assert summary.suppressed == 1
        assert canvas.refresh_calls == 1
        assert publisher.calls == []
    finally:
        engine.dispose()


def test_downtime_crossing_sends_only_newest_checkpoint(tmp_path: Path) -> None:
    due_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    now_ref = [due_at - timedelta(hours=30)]
    engine, sessions, _canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=due_at,
    )
    try:
        first = service.run_once()
        now_ref[0] = due_at - timedelta(hours=11)
        second = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            assert event is not None
            assert event.checkpoint_minutes == 720
        assert first.sent == 0
        assert second.sent == 1
        assert len(publisher.calls) == 1
    finally:
        engine.dispose()


def test_dry_run_persists_without_publishing(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    engine, sessions, _canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(minutes=30),
        dry_run=True,
    )
    try:
        summary = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            assert event is not None and event.status == "dry_run"
        assert summary.dry_run == 1
        assert publisher.calls == []
    finally:
        engine.dispose()
