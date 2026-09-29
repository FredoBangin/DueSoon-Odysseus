from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.discord import DiscordPublishError
from src.duesoon.notifications.mirror import DiscordMirrorService
from src.duesoon.notifications.ntfy import PublishResult
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import create_engine_from_settings, create_schema, session_factory
from src.duesoon.persistence.models import Assignment, Course, NotificationDelivery, NotificationMirrorContext


class Publisher:
    def __init__(self, errors=()):
        self.calls = []
        self.errors = list(errors)

    def publish(self, **payload):
        self.calls.append(payload)
        if self.errors:
            raise self.errors.pop(0)
        return PublishResult("message-1")


def build(tmp_path, *, errors=(), dry_run=False):
    now = [datetime(2026, 9, 28, 12, tzinfo=UTC)]
    due = now[0] + timedelta(hours=5)
    settings = DueSoonSettings(
        _env_file=None, environment="test", database_url=f"sqlite:///{tmp_path / 'mirror.db'}",
        dry_run=dry_run, ntfy_enabled=True, ntfy_url="https://notify.example.test",
        ntfy_topic="fake-topic", ntfy_token="fake-token", discord_enabled=True,
        discord_webhook_url="https://discord.com/api/webhooks/123/fake-secret",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    with sessions() as session:
        course = Course(canvas_course_id="42", name="Sample Course")
        session.add(course)
        session.flush()
        assignment = Assignment(canvas_assignment_id="99", course_id=course.id,
                                canonical_title="Sample Lab", canvas_due_at=due, published=True,
                                first_seen_at=now[0], last_seen_at=now[0])
        session.add(assignment)
        session.commit()
        assignment_id = assignment.id
    calls, states = [], ["not_submitted"]
    def recheck(key):
        calls.append(key)
        return states[0]
    primary, discord = Publisher(), Publisher(errors)
    mirror = DiscordMirrorService(settings, sessions, discord, submission_recheck=recheck, clock=lambda: now[0])
    service = NotificationService(settings, sessions, primary, discord_mirror=mirror)
    return engine, sessions, now, due, assignment_id, calls, states, primary, discord, mirror, service


def send(service, assignment_id, due):
    return service.send_reminder(idempotency_key="checkpoint-1", title="Sample", message="Sample deadline",
                                 priority=3, assignment_deadlines={assignment_id: due}, expires_at=due)


def row(sessions):
    with sessions() as session:
        return session.scalar(select(NotificationDelivery).where(NotificationDelivery.provider == "discord"))


def test_mirror_has_independent_audit_dedup_and_immediate_recheck(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path)
    try:
        first, second = send(service, key, due), send(service, key, due)
        assert first.status == "sent" and second.status == "already_sent"
        assert len(primary.calls) == len(discord.calls) == 1
        assert checks == [key]
        assert row(sessions).status == "sent"
        with sessions() as session:
            context = session.get(NotificationMirrorContext, row(sessions).id)
            assert context.submission_recheck_statuses == {str(key): "not_submitted"}
            assert context.submission_rechecked_at is not None
        assert mirror.run_once() == 0
    finally:
        engine.dispose()


def test_retry_respects_backoff_and_rechecks_without_resending_ntfy(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, errors=[DiscordPublishError("rate limited", retryable=True, retry_after=90)])
    try:
        assert send(service, key, due).status == "sent"
        assert row(sessions).status == "retry_scheduled"
        now[0] += timedelta(seconds=89)
        assert mirror.run_once() == 0
        now[0] += timedelta(seconds=1)
        assert mirror.run_once() == 1
        assert row(sessions).status == "sent"
        assert len(primary.calls) == 1 and len(discord.calls) == 2
        assert checks == [key, key]
    finally:
        engine.dispose()


def test_completed_work_suppresses_mirror_even_when_ntfy_already_sent(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path)
    try:
        states[0] = "submitted"
        assert send(service, key, due).status == "sent"
        assert row(sessions).status == "suppressed_submission"
        assert len(primary.calls) == 1 and discord.calls == []
    finally:
        engine.dispose()


def test_changed_deadline_suppresses_retry(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, errors=[DiscordPublishError("connect", retryable=True)])
    try:
        send(service, key, due)
        with sessions() as session:
            session.get(Assignment, key).canvas_due_at = due + timedelta(days=1)
            session.commit()
        now[0] += timedelta(seconds=31)
        mirror.run_once()
        assert row(sessions).status == "suppressed_stale"
        assert len(discord.calls) == 1
    finally:
        engine.dispose()


def test_timeout_and_restart_never_replay_unknown_outcomes(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, errors=[DiscordPublishError("timeout", ambiguous=True)])
    try:
        send(service, key, due)
        assert row(sessions).status == "unknown"
        now[0] += timedelta(minutes=5)
        mirror.run_once()
        assert len(discord.calls) == 1
        with sessions() as session:
            session.get(NotificationDelivery, row(sessions).id).status = "pending"
            session.commit()
        mirror.recover_pending()
        assert row(sessions).status == "unknown"
        assert mirror.run_once() == 0
    finally:
        engine.dispose()


def test_dry_run_never_contacts_either_provider(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, dry_run=True)
    try:
        assert send(service, key, due).status == "dry_run"
        assert row(sessions).status == "dry_run"
        assert primary.calls == discord.calls == []
    finally:
        engine.dispose()


def test_expired_or_missing_context_never_sends_school_message(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path)
    try:
        now[0] = due
        send(service, key, due)
        assert row(sessions).status == "suppressed_stale"
        assert discord.calls == []
        service.send_reminder(idempotency_key="no-context", title="Sample", message="Sample", priority=3)
        with sessions() as session:
            missing = session.scalars(select(NotificationDelivery).where(NotificationDelivery.provider == "discord").order_by(NotificationDelivery.id)).all()[-1]
            assert missing.error_code == "missing_recheck_context"
    finally:
        engine.dispose()


def test_retry_attempts_are_bounded(tmp_path):
    errors = [DiscordPublishError("rate limited", retryable=True)] * 3
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, errors=errors)
    try:
        send(service, key, due)
        for _ in range(2):
            now[0] += timedelta(minutes=5)
            mirror.run_once()
        assert row(sessions).status == "failed"
        assert len(discord.calls) == 3 and len(primary.calls) == 1
        assert mirror.run_once() == 0
    finally:
        engine.dispose()


def test_unknown_submission_does_not_publish_until_fresh_recheck(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path)
    try:
        states[0] = "unknown"
        send(service, key, due)
        assert row(sessions).status == "retry_scheduled"
        assert row(sessions).error_code == "submission_status_unknown"
        assert discord.calls == []
        states[0] = "not_submitted"
        now[0] += timedelta(seconds=31)
        mirror.run_once()
        assert row(sessions).status == "sent"
        assert checks == [key, key]
        assert len(discord.calls) == len(primary.calls) == 1
    finally:
        engine.dispose()


def test_retry_after_expiry_suppresses_without_resending(tmp_path):
    errors = [DiscordPublishError("rate limited", retryable=True, retry_after=86400)]
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path, errors=errors)
    try:
        send(service, key, due)
        assert row(sessions).status == "suppressed_stale"
        assert row(sessions).error_code == "retry_after_expiry"
        now[0] += timedelta(days=1)
        assert mirror.run_once() == 0
        assert len(discord.calls) == len(primary.calls) == 1
    finally:
        engine.dispose()


def test_schema_expansion_preserves_previous_deliveries_and_does_not_replay_them(tmp_path):
    engine, sessions, now, due, key, checks, states, primary, discord, mirror, service = build(tmp_path)
    try:
        old_service = NotificationService(service._settings, sessions, primary)
        send(old_service, key, due)
        NotificationMirrorContext.__table__.drop(engine)
        create_schema(engine)
        create_schema(engine)
        assert send(service, key, due).status == "already_sent"
        with sessions() as session:
            assert len(session.scalars(select(NotificationDelivery)).all()) == 1
        assert discord.calls == []
    finally:
        engine.dispose()
