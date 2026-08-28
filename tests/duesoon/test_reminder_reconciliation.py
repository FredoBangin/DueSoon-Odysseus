from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.canvas.sync import CanvasSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.ntfy import PublishResult
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    ReminderEvent,
    SchedulerState,
    SourceRecord,
)
from src.duesoon.reminders.service import ReminderService


class MutableCanvasClient:
    def __init__(self, due_at: datetime | None) -> None:
        self.due_at = due_at
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
                "due_at": (
                    self.due_at.isoformat().replace("+00:00", "Z")
                    if self.due_at is not None
                    else None
                ),
                "points_possible": 25,
                "submission_types": ["online_upload"],
                "grading_type": "points",
                "published": True,
                "workflow_state": "published",
                "updated_at": "2026-08-28T12:00:00Z",
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
            "workflow_state": "unsubmitted",
            "missing": False,
            "late": False,
        }


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def publish(self, **payload: object) -> PublishResult:
        self.calls.append(payload)
        return PublishResult(provider_message_id=f"provider-{len(self.calls)}")


def build_service(
    tmp_path: Path,
    *,
    now_ref: list[datetime],
    due_at: datetime | None,
    assignment_projector=project_canvas_assignment,
):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'reconciliation.db').as_posix()}",
        dry_run=False,
        ntfy_enabled=True,
        ntfy_url="https://notify.example.test",
        ntfy_topic="private-topic",
        ntfy_token="ntfy-token",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    canvas = MutableCanvasClient(due_at)
    sync = CanvasSyncService(canvas, sessions, clock=lambda: now_ref[0])
    publisher = RecordingPublisher()
    notifications = NotificationService(settings, sessions, publisher)
    service = ReminderService(
        sessions,
        sync,
        notifications,
        clock=lambda: now_ref[0],
        assignment_projector=assignment_projector,
    )
    return engine, sessions, canvas, sync, publisher, service


def seed_old_event(sessions, *, deadline: datetime, evaluated_at: datetime) -> int:
    with sessions() as session:
        assignment_id = session.scalar(select(Assignment.id))
        assert assignment_id is not None
        event = ReminderEvent(
            assignment_id=assignment_id,
            deadline_at=deadline,
            checkpoint_minutes=1440,
            status="claimed",
            reason="Old deadline reminder",
            evaluated_at=evaluated_at,
        )
        session.add(event)
        session.add(
            SchedulerState(
                key="canvas_reminders",
                last_successful_at=evaluated_at,
            )
        )
        session.commit()
        return event.id


def test_reminders_use_operational_deadline_not_canvas_deadline(tmp_path: Path) -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    canvas_due = now + timedelta(days=2)
    operational_due = now + timedelta(hours=5)

    def project_operational(assignment: Assignment):
        return replace(
            project_canvas_assignment(assignment),
            effective_due_at=operational_due,
            operational_due_at=operational_due,
            deadline_source_summary="Verified professor correction",
        )

    engine, sessions, canvas, _sync, publisher, service = build_service(
        tmp_path,
        now_ref=[now],
        due_at=canvas_due,
        assignment_projector=project_operational,
    )
    try:
        summary = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            assert event is not None
            assert event.deadline_at.replace(tzinfo=UTC) == operational_due
            assert event.checkpoint_minutes == 360
        assert summary.sent == 1
        assert canvas.refresh_calls == 1
        assert len(publisher.calls) == 1
    finally:
        engine.dispose()


def test_earlier_deadline_cancels_old_event_and_sends_only_one_now(
    tmp_path: Path,
) -> None:
    now_ref = [datetime(2026, 8, 28, 12, 0, tzinfo=UTC)]
    old_due = now_ref[0] + timedelta(days=2)
    engine, sessions, canvas, sync, publisher, service = build_service(
        tmp_path,
        now_ref=now_ref,
        due_at=old_due,
    )
    try:
        sync.sync()
        old_event_id = seed_old_event(
            sessions,
            deadline=old_due,
            evaluated_at=now_ref[0],
        )
        now_ref[0] += timedelta(minutes=1)
        new_due = now_ref[0] + timedelta(hours=5)
        canvas.due_at = new_due

        summary = service.run_once()

        with sessions() as session:
            events = session.scalars(
                select(ReminderEvent).order_by(ReminderEvent.id)
            ).all()
            assert events[0].id == old_event_id
            assert events[0].status == "cancelled_deadline_change"
            assert events[1].deadline_at.replace(tzinfo=UTC) == new_due
            assert events[1].checkpoint_minutes == 360
            assert events[1].status == "sent"
        assert summary.sent == 1
        assert canvas.refresh_calls == 1
        assert len(publisher.calls) == 1
    finally:
        engine.dispose()


def test_later_deadline_cancels_old_event_without_immediate_send(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 28, 12, 0, tzinfo=UTC)]
    old_due = now_ref[0] + timedelta(hours=5)
    engine, sessions, canvas, sync, publisher, service = build_service(
        tmp_path,
        now_ref=now_ref,
        due_at=old_due,
    )
    try:
        sync.sync()
        old_event_id = seed_old_event(
            sessions,
            deadline=old_due,
            evaluated_at=now_ref[0],
        )
        now_ref[0] += timedelta(minutes=1)
        canvas.due_at = now_ref[0] + timedelta(days=3)

        summary = service.run_once()

        with sessions() as session:
            event = session.get(ReminderEvent, old_event_id)
            assert event is not None
            assert event.status == "cancelled_deadline_change"
            assert session.scalar(select(ReminderEvent).where(ReminderEvent.id != old_event_id)) is None
        assert summary.sent == 0
        assert canvas.refresh_calls == 0
        assert publisher.calls == []
    finally:
        engine.dispose()


def test_removed_deadline_cancels_old_event_without_submission_recheck(
    tmp_path: Path,
) -> None:
    now_ref = [datetime(2026, 8, 28, 12, 0, tzinfo=UTC)]
    old_due = now_ref[0] + timedelta(hours=5)
    engine, sessions, canvas, sync, publisher, service = build_service(
        tmp_path,
        now_ref=now_ref,
        due_at=old_due,
    )
    try:
        sync.sync()
        old_event_id = seed_old_event(
            sessions,
            deadline=old_due,
            evaluated_at=now_ref[0],
        )
        now_ref[0] += timedelta(minutes=1)
        canvas.due_at = None

        summary = service.run_once()

        with sessions() as session:
            event = session.get(ReminderEvent, old_event_id)
            assert event is not None
            assert event.status == "cancelled_deadline_change"
            assert event.reason == "Operational deadline was removed"
        assert summary.sent == 0
        assert canvas.refresh_calls == 0
        assert publisher.calls == []
    finally:
        engine.dispose()


def test_reminder_uses_persisted_professor_evidence_deadline(tmp_path: Path) -> None:
    now_ref = [datetime(2026, 8, 28, 13, 0, tzinfo=UTC)]
    canvas_due = now_ref[0] + timedelta(days=2)
    evidence_due = now_ref[0] + timedelta(hours=5)
    engine, sessions, canvas, sync, publisher, service = build_service(
        tmp_path,
        now_ref=now_ref,
        due_at=canvas_due,
    )
    try:
        sync.sync()
        with sessions() as session:
            assignment = session.scalar(select(Assignment))
            assert assignment is not None
            source = SourceRecord(
                source_system="canvas",
                source_type="inbox_message",
                external_id="inbox-correction-1",
                content_hash="inbox-source-hash",
                source_published_at=now_ref[0] - timedelta(minutes=30),
                observed_at=now_ref[0],
                raw_payload={"private_message": "not-rendered"},
            )
            claim = Claim(
                source_record=source,
                claim_type="deadline_moved_earlier_to",
                normalized_value={
                    "due_at": evidence_due.isoformat(),
                    "precision": "exact_datetime",
                },
                source_published_at=now_ref[0] - timedelta(minutes=30),
                source_observed_at=now_ref[0],
                extraction_method="deterministic_fixture",
                extractor_version="claims-v1",
                extraction_confidence=0.99,
                validation_status="validated",
                claim_fingerprint="correction-claim-hash",
            )
            session.add(
                AssignmentEvidence(
                    assignment=assignment,
                    claim=claim,
                    course_match_score=1.0,
                    assignment_match_score=1.0,
                    authority_score=1.0,
                    explicitness_score=1.0,
                    precision="exact_datetime",
                    disposition="admitted",
                    explanation="Verified professor correction.",
                )
            )
            session.commit()

        summary = service.run_once()

        with sessions() as session:
            event = session.scalar(select(ReminderEvent))
            assert event is not None
            assert event.deadline_at.replace(tzinfo=UTC) == evidence_due
            assert event.checkpoint_minutes == 360
            assert event.status == "sent"
        assert summary.sent == 1
        assert canvas.refresh_calls == 1
        assert len(publisher.calls) == 1
    finally:
        engine.dispose()
