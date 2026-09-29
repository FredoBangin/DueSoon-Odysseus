"""Routine reminders remain private; explicit transport tests still mirror."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.discord import DiscordPublishError
from src.duesoon.notifications.mirror import DiscordMirrorService
from src.duesoon.notifications.ntfy import PublishResult
from src.duesoon.notifications.service import NotificationService
from src.duesoon.persistence.database import create_engine_from_settings, create_schema, session_factory
from src.duesoon.persistence.models import NotificationDelivery, NotificationMirrorContext


class Publisher:
    def __init__(self, errors=()):
        self.calls, self.errors = [], list(errors)

    def publish(self, **payload):
        self.calls.append(payload)
        if self.errors:
            raise self.errors.pop(0)
        return PublishResult("message-1")


@pytest.fixture
def setup(tmp_path):
    settings = DueSoonSettings(_env_file=None, environment="test", dry_run=False,
        database_url=f"sqlite:///{tmp_path / 'mirror.db'}", ntfy_enabled=True,
        ntfy_url="https://notify.example.test", ntfy_topic="test", ntfy_token="fake-token",
        discord_enabled=True, discord_webhook_url="https://discord.com/api/webhooks/123/fake-secret")
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    now = [datetime(2026, 9, 29, 12, tzinfo=UTC)]
    primary, discord = Publisher(), Publisher()
    mirror = DiscordMirrorService(settings, sessions, discord, clock=lambda: now[0])
    service = NotificationService(settings, sessions, primary, discord_mirror=mirror)
    yield settings, sessions, now, primary, discord, mirror, service
    engine.dispose()


@pytest.mark.parametrize("kind", ["deadline_checkpoint", "adaptive_deadline_change", "daily_digest", "academic_update_urgent"])
def test_routine_ntfy_does_not_mirror(setup, kind):
    _, sessions, _, primary, discord, mirror, service = setup
    result = service.send_reminder(idempotency_key=kind, title="School", message="Exact verified dates", priority=3, notification_kind=kind)
    assert result.status == "sent" and len(primary.calls) == 1
    assert not discord.calls and mirror.run_once() == 0
    with sessions() as session:
        assert len(session.scalars(select(NotificationDelivery)).all()) == 1


def send_test(service):
    return service.send_test(idempotency_key="explicit-test", title="Test", message="No student data", priority=3)


def discord_row(sessions):
    with sessions() as session:
        return session.scalar(select(NotificationDelivery).where(NotificationDelivery.provider == "discord"))


def test_explicit_test_dedup_and_retry(setup):
    _, sessions, now, primary, discord, mirror, service = setup
    discord.errors = [DiscordPublishError("rate limited", retryable=True, retry_after=90)]
    send_test(service)
    send_test(service)
    assert discord_row(sessions).status == "retry_scheduled"
    now[0] += timedelta(seconds=89)
    assert mirror.run_once() == 0
    now[0] += timedelta(seconds=1)
    assert mirror.run_once() == 1
    assert discord_row(sessions).status == "sent"
    assert len(primary.calls) == 1 and len(discord.calls) == 2


def test_unknown_and_interrupted_sends_never_replay(setup):
    _, sessions, now, _, discord, mirror, service = setup
    discord.errors = [DiscordPublishError("timeout", ambiguous=True)]
    send_test(service)
    assert discord_row(sessions).status == "unknown"
    with sessions() as session:
        session.get(NotificationDelivery, discord_row(sessions).id).status = "pending"
        session.commit()
    mirror.recover_pending()
    now[0] += timedelta(minutes=5)
    assert mirror.run_once() == 0 and len(discord.calls) == 1


def test_dry_run_never_contacts_either_provider(setup):
    settings, sessions, _, primary, discord, _, service = setup
    settings.dry_run = True
    assert send_test(service).status == "dry_run"
    assert discord_row(sessions).status == "dry_run"
    assert not primary.calls and not discord.calls


def test_rollout_cancels_old_routine_retries_preserving_history(setup):
    _, sessions, now, _, discord, mirror, _ = setup
    with sessions() as session:
        row = NotificationDelivery(dedup_key="old-daily", notification_kind="daily_digest", status="retry_scheduled",
            rendered_title="Old", rendered_body="Historical body unchanged", priority=3, provider="discord", attempted_at=now[0])
        session.add(row)
        session.flush()
        session.add(NotificationMirrorContext(delivery_id=row.id, assignment_ids=[], deadline_versions={},
            attempts=1, expires_at=now[0]+timedelta(hours=1), next_attempt_at=now[0]))
        session.commit()
    mirror.recover_pending()
    assert discord_row(sessions).status == "suppressed_policy"
    assert discord_row(sessions).rendered_body == "Historical body unchanged"
    assert mirror.run_once() == 0 and not discord.calls
