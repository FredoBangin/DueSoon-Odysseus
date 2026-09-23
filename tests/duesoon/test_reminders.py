from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from src.duesoon.reminders.checkpoints import (
    CHECKPOINT_MINUTES,
    adaptive_interval_key,
    crossed_checkpoint,
)
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import NtfyPublishError, PublishResult
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import NotificationDelivery, ReminderEvent, SchedulerState
from src.duesoon.reminders.service import ReminderService, _daily_digest_body


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


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (timedelta(hours=18), "1440:720"),
        (timedelta(hours=5), "360:60"),
        (timedelta(minutes=50), "60:15"),
        (timedelta(minutes=70), None),
        (timedelta(minutes=40), None),
        (timedelta(minutes=10), None),
    ],
)
def test_adaptive_interval_requires_30_minutes_before_next_standard_checkpoint(
    remaining: timedelta, expected: str | None
) -> None:
    assert adaptive_interval_key(remaining) == expected


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


class RetryPublisher(ReminderPublisher):
    def publish(self, **payload: object) -> PublishResult:
        self.calls.append(payload)
        if len(self.calls) == 1:
            raise NtfyPublishError("ntfy rate limited request", retryable=True)
        return PublishResult(provider_message_id="provider-reminder-retry")


def build_reminder_service(
    tmp_path: Path,
    *,
    now_ref: list[datetime],
    due_at: datetime,
    refresh_state: str = "unsubmitted",
    dry_run: bool = False,
    daily_digest_enabled: bool = False,
    publisher: ReminderPublisher | None = None,
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
        daily_digest_enabled=daily_digest_enabled,
        daily_digest_hour=8,
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    canvas = ReminderCanvasClient(due_at, refresh_state)
    sync = CanvasSyncService(canvas, sessions, clock=lambda: now_ref[0])
    publisher = publisher or ReminderPublisher()
    notifications = NotificationService(settings, sessions, publisher)
    service = ReminderService(
        sessions,
        sync,
        notifications,
        settings=settings,
        clock=lambda: now_ref[0],
    )
    return engine, sessions, canvas, publisher, service


def test_daily_digest_sends_once_after_local_hour_with_immediate_recheck(
    tmp_path: Path,
) -> None:
    now_ref = [datetime(2026, 8, 27, 11, 59, tzinfo=UTC)]  # 7:59 AM EDT
    engine, sessions, canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(days=3),
        daily_digest_enabled=True,
    )
    try:
        before_hour = service.run_once()
        now_ref[0] = datetime(2026, 8, 27, 12, 1, tzinfo=UTC)
        first = service.run_once()
        second = service.run_once()

        with sessions() as session:
            delivery = session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_kind == "daily_digest"
                )
            )
            assert delivery is not None
            assert delivery.status == "sent"
            assert delivery.dedup_key == "daily-digest:2026-08-27"
            assert "Lab 1" in delivery.rendered_body
            assert delivery.rendered_title == "DueSoon daily briefing · Aug 27, 2026"
            assert delivery.rendered_body == (
                "Due This Week\nNetwork Security — Lab 1 — Sun, Aug 30 at 7:59 AM EDT"
            )
        assert before_hour.sent == 0
        assert first.sent == 1
        assert second.sent == 0
        assert canvas.refresh_calls == 1
        assert len(publisher.calls) == 1
        assert publisher.calls[0]["message"] == delivery.rendered_body
    finally:
        engine.dispose()


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


def test_retryable_delivery_rechecks_canvas_again_before_retry(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    retry_publisher = RetryPublisher()
    engine, sessions, canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(hours=5),
        publisher=retry_publisher,
    )
    try:
        with pytest.raises(NtfyPublishError):
            service.run_once()
        now_ref[0] += timedelta(minutes=1)
        recovered = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            delivery = session.scalar(select(NotificationDelivery))
            assert event is not None and event.status == "sent"
            assert delivery is not None and delivery.status == "sent"
        assert recovered.sent == 1
        assert canvas.refresh_calls == 2
        assert len(publisher.calls) == 2
    finally:
        engine.dispose()


def test_digest_formats_operational_deadlines_in_local_timezone_across_dst() -> None:
    assignment = SimpleNamespace(
        course=SimpleNamespace(name="TEST101-2026-99 | Sample Course"),
        canonical_title="Project\n  one", due_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    deadlines = [
        datetime(2026, 9, 28, 3, 59, tzinfo=UTC),
        datetime(2026, 11, 2, 4, 59, tzinfo=UTC),
    ]
    body = _daily_digest_body(
        [(assignment, SimpleNamespace(operational_due_at=due)) for due in deadlines],
        datetime(2026, 9, 23, 8, tzinfo=ZoneInfo("America/New_York")),
    )
    assert body.split("\n\n") == [
        "Due This Week\nSample Course — Project one — Sun, Sep 27 at 11:59 PM EDT",
        "Due Later\nSample Course — Project one — Sun, Nov 1 at 11:59 PM EST",
    ]


def test_digest_groups_chronologically_flags_near_work_and_keeps_review_separate() -> None:
    zone = ZoneInfo("America/New_York")
    local_now = datetime(2026, 9, 23, 8, tzinfo=zone)

    def item(title: str, due: datetime, course_id: int = 1):
        return (
            SimpleNamespace(
                course_id=course_id,
                course=SimpleNamespace(name="TEST101-2026-99 | Sample Course"),
                canonical_title=title,
            ),
            SimpleNamespace(operational_due_at=due.astimezone(UTC)),
        )

    body = _daily_digest_body(
        [
            item("Term paper", datetime(2026, 9, 28, 23, 59, tzinfo=zone)),
            item("Mid Exam", datetime(2026, 9, 27, 23, 59, tzinfo=zone)),
            item("REVIEW Mid Exam", datetime(2026, 9, 26, 23, 59, tzinfo=zone)),
            item("Today's lab", datetime(2026, 9, 23, 23, 59, tzinfo=zone)),
            item("Next year", datetime(2027, 1, 4, 23, 59, tzinfo=zone)),
        ],
        local_now,
    )
    assert body == (
        "Due Today\n"
        "⚠️ Sample Course — Today's lab — Wed, Sep 23 at 11:59 PM EDT\n\n"
        "Due This Week\n"
        "Sample Course — REVIEW Mid Exam (review for Mid Exam) — Sat, Sep 26 at 11:59 PM EDT\n"
        "Sample Course — Mid Exam — Sun, Sep 27 at 11:59 PM EDT\n\n"
        "Due Later\n"
        "Sample Course — Term paper — Mon, Sep 28 at 11:59 PM EDT\n"
        "Sample Course — Next year — Mon, Jan 4, 2027 at 11:59 PM EST"
    )


def test_digest_exact_48_hour_boundary_and_overdue_dates_are_explicit() -> None:
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 9, 23, 8, tzinfo=zone)
    assignment = SimpleNamespace(
        course=SimpleNamespace(name="Sample Course"), canonical_title="Lab",
    )
    body = _daily_digest_body(
        [
            (assignment, SimpleNamespace(operational_due_at=(now + timedelta(hours=48)).astimezone(UTC))),
            (assignment, SimpleNamespace(operational_due_at=(now - timedelta(days=1)).astimezone(UTC))),
        ],
        now,
    )
    assert body == (
        "Due Today\n⚠️ OVERDUE Sample Course — Lab — Tue, Sep 22 at 8:00 AM EDT\n\n"
        "Due This Week\n⚠️ Sample Course — Lab — Fri, Sep 25 at 8:00 AM EDT"
    )


def test_long_digest_keeps_whole_dates_and_accounts_for_omitted_items() -> None:
    assignment = SimpleNamespace(
        course=SimpleNamespace(name="Long course name " * 50), canonical_title="Long title " * 100,
    )
    effective = SimpleNamespace(operational_due_at=datetime(2027, 1, 1, 4, 59, tzinfo=UTC))
    body = _daily_digest_body(
        [(assignment, effective)] * 10,
        datetime(2026, 12, 30, 8, tzinfo=ZoneInfo("America/New_York")),
    )
    blocks = body.split("\n\n")
    assert len(body) <= 1000
    assert blocks[-1].startswith("+ ") and blocks[-1].endswith(" more in dashboard.")
    assert body.startswith("Due This Week\n")
    for line in blocks[0].splitlines()[1:]:
        assert line.endswith("Thu, Dec 31 at 11:59 PM EST")


def test_daily_digest_suppresses_when_configured_timezone_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ref = [datetime(2026, 8, 27, 12, 1, tzinfo=UTC)]
    engine, _, canvas, publisher, service = build_reminder_service(
        tmp_path,
        now_ref=now_ref,
        due_at=now_ref[0] + timedelta(days=3),
        daily_digest_enabled=True,
    )

    def missing_timezone(_: str):
        from zoneinfo import ZoneInfoNotFoundError

        raise ZoneInfoNotFoundError("test timezone unavailable")

    monkeypatch.setattr("src.duesoon.reminders.service.ZoneInfo", missing_timezone)
    try:
        summary = service.run_once()

        assert summary.sent == 0
        assert canvas.refresh_calls == 0
        assert publisher.calls == []
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
