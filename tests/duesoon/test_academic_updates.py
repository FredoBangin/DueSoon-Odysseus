"""Evidence, cadence, safety, privacy, and follow-up contract for Bob updates."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.notifications.discord import DiscordPublishError
from src.duesoon.notifications.service import NotificationService
from src.duesoon.notifications.updates import AcademicUpdateService, announcement_excerpt
from src.duesoon.persistence.database import create_engine_from_settings, create_schema, session_factory
from src.duesoon.persistence.models import AcademicNote, AcademicUpdateEvent, Assignment, Course, NotificationDelivery, NotificationMirrorContext, ReminderEvent, SourceRecord
from tests.duesoon.test_discord_mirror import Publisher
from tests.duesoon.test_dashboard_mvp import attach_deadline_evidence


@pytest.fixture
def env(tmp_path):
    now = [datetime(2026, 9, 29, 12, tzinfo=UTC)]
    settings = DueSoonSettings(_env_file=None, environment="test", dry_run=False, public_origin="https://due.test",
        database_url=f"sqlite:///{tmp_path / 'updates.db'}", ntfy_enabled=True,
        ntfy_url="https://notify.example.test", ntfy_topic="fake", ntfy_token="fake",
        discord_enabled=True, discord_webhook_url="https://discord.com/api/webhooks/123/fake-secret")
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    with sessions() as session:
        course = Course(canvas_course_id="42", name="Sample | Security")
        assignment = Assignment(canvas_assignment_id="99", course=course, canonical_title="Final exam",
            canvas_due_at=now[0]+timedelta(days=7), published=True, first_seen_at=now[0], last_seen_at=now[0])
        session.add(assignment)
        session.commit()
        course_id, assignment_id = course.id, assignment.id
    primary, discord, checks = Publisher(), Publisher(), []
    states = ["not_submitted"]
    def recheck(key):
        checks.append(key)
        if isinstance(states[0], Exception):
            raise states[0]
        return states[0]
    service = AcademicUpdateService(settings, sessions, discord, NotificationService(settings, sessions, primary),
        submission_recheck=recheck, clock=lambda: now[0])
    yield SimpleNamespace(settings=settings, sessions=sessions, now=now, primary=primary, discord=discord,
        checks=checks, states=states, service=service, assignment_id=assignment_id, course_id=course_id, engine=engine)
    engine.dispose()


def announcement(env, external_id="new", *, version=1, published=None, message="Read the updated study guide."):
    with env.sessions() as session:
        source = SourceRecord(source_system="canvas", source_type="announcement", external_id=external_id,
            course_id=env.course_id, content_hash=external_id+str(version), version=version,
            observed_at=env.now[0], source_published_at=published or env.now[0], raw_payload={"title":"Professor update", "message":message})
        session.add(source)
        session.commit()
        return source.id


def rows(env):
    with env.sessions() as session:
        return list(session.scalars(select(NotificationDelivery).where(NotificationDelivery.provider == "discord").order_by(NotificationDelivery.id)).all())


def change_due(env, due):
    with env.sessions() as session:
        session.get(Assignment, env.assignment_id).canvas_due_at = due
        session.commit()


def start_change(env):
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    change_due(env, env.now[0]+timedelta(days=3))


def test_no_historical_replay_no_filler_all_announcements_and_48h_restart(env):
    announcement(env, "historical")
    assert env.service.run_once() == 0 and not rows(env)
    env.now[0] += timedelta(minutes=1)
    announcement(env)
    env.service.run_once()
    assert len(env.discord.calls) == 1 and not env.primary.calls
    body = env.discord.calls[0]["message"]
    assert "Source excerpt (not AI analysis)" in body and "Tuesday, September 29 at 8:01 AM EDT" in body
    assert "study guide" in body and "/app/assistant?update=" in body
    env.now[0] += timedelta(minutes=1)
    announcement(env, "second", message="Optional office hours have changed.")
    announcement(env, "old-import", published=env.now[0]-timedelta(days=30))
    env.service.run_once()
    assert len(env.discord.calls) == 1
    env.service = AcademicUpdateService(env.settings, env.sessions, env.discord, env.service.notifications, clock=lambda:env.now[0])
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert len(env.discord.calls) == 2 and "office hours" in env.discord.calls[-1]["message"]
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert len(env.discord.calls) == 2


def test_edited_old_announcement_supersedes_queued_version(env):
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    announcement(env, message="Original instruction")
    announcement(env, version=2, published=env.now[0]-timedelta(days=30), message="Revised instruction")
    env.service.run_once()
    assert len(env.discord.calls) == 1
    assert "Revised instruction" in env.discord.calls[0]["message"] and "Original instruction" not in env.discord.calls[0]["message"]


def test_announcement_posted_between_content_syncs_is_not_lost(env):
    env.service.run_once()
    published = env.now[0]+timedelta(minutes=1)
    env.now[0] += timedelta(minutes=5)
    env.service.run_once()
    env.now[0] += timedelta(minutes=25)
    announcement(env, published=published)
    env.service.run_once()
    assert len(env.discord.calls) == 1


def test_unknown_publication_date_is_flagged_not_guessed(env):
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    key = announcement(env)
    with env.sessions() as session:
        session.get(SourceRecord,key).source_published_at = None
        session.commit()
    env.service.run_once()
    assert "Posted date unknown — check Canvas" in env.discord.calls[0]["message"]


def test_additive_table_creation_preserves_old_deliveries(env):
    with env.sessions() as session:
        row = NotificationDelivery(dedup_key="old", notification_kind="daily_digest", provider="ntfy",
            rendered_title="Historical", rendered_body="Preserve exactly", priority=3, status="sent", attempted_at=env.now[0])
        session.add(row)
        session.commit()
        old_id = row.id
    AcademicUpdateEvent.__table__.drop(env.engine)
    create_schema(env.engine)
    create_schema(env.engine)
    with env.sessions() as session:
        assert session.get(NotificationDelivery,old_id).rendered_body == "Preserve exactly"
        assert list(session.scalars(select(AcademicUpdateEvent))) == []


@pytest.mark.parametrize("state,expected", [("submitted","suppressed_stale"),("graded","suppressed_stale"),("unknown","retry_scheduled"),(RuntimeError("private data"),"retry_scheduled")])
def test_submission_recheck_cannot_send_completed_unknown_or_failed(env, state, expected):
    start_change(env)
    env.states[0] = state
    env.service.run_once()
    assert rows(env)[0].status == expected and not env.discord.calls
    assert env.checks == [env.assignment_id]


def test_retry_is_safe_bounded_and_does_not_resend_ntfy(env):
    start_change(env)
    env.discord.errors = [DiscordPublishError("rate limited", retryable=True, retry_after=90)] * 3
    env.service.run_once()
    env.now[0] += timedelta(seconds=89)
    env.service.run_once()
    assert len(env.discord.calls) == 1
    env.now[0] += timedelta(seconds=1)
    env.service.run_once()
    env.now[0] += timedelta(seconds=90)
    env.service.run_once()
    assert rows(env)[0].status == "failed" and len(env.discord.calls) == 3 and not env.primary.calls
    assert env.checks == [env.assignment_id]*3


def test_timeout_never_replays_and_dry_run_never_contacts_providers(env):
    start_change(env)
    env.discord.errors = [DiscordPublishError("timeout", ambiguous=True)]
    env.service.run_once()
    env.now[0] += timedelta(minutes=5)
    env.service.run_once()
    assert rows(env)[0].status == "unknown" and len(env.discord.calls) == 1
    env.settings.dry_run = True
    env.now[0] += timedelta(hours=48)
    change_due(env, env.now[0]+timedelta(days=2))
    env.service.run_once()
    assert rows(env)[-1].status == "dry_run" and len(env.discord.calls) == 1 and not env.primary.calls


def test_changed_deadline_during_recheck_cannot_send_old_version(env):
    start_change(env)
    def recheck(key):
        change_due(env, env.now[0]+timedelta(days=5))
        return "not_submitted"
    env.service.recheck = recheck
    env.service.run_once()
    assert rows(env)[0].status == "suppressed_stale" and not env.discord.calls


def test_urgent_ntfy_bypasses_cadence_with_recheck_and_dedup(env):
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    announcement(env)
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    change_due(env, env.now[0]+timedelta(hours=24))
    env.service.run_once()
    assert len(env.discord.calls) == 1 and len(env.primary.calls) == 1 and env.checks == [env.assignment_id]
    assert "Wednesday, September 30 at 8:02 AM EDT" in env.primary.calls[0]["message"]
    env.service.run_once()
    assert len(env.primary.calls) == 1


def test_urgent_reuses_existing_checkpoint(env):
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    due = env.now[0]+timedelta(hours=24)
    change_due(env, due)
    with env.sessions() as session:
        delivery = NotificationDelivery(dedup_key="checkpoint", notification_kind="deadline_checkpoint", provider="ntfy",
            rendered_title="School", rendered_body="Exact date", priority=3, status="sent", attempted_at=env.now[0])
        session.add(delivery)
        session.flush()
        session.add(ReminderEvent(assignment_id=env.assignment_id, deadline_at=due, checkpoint_minutes=1440,
            status="sent", reason="Verified", evaluated_at=env.now[0], delivery_id=delivery.id))
        session.commit()
    env.service.run_once()
    assert not env.primary.calls


def test_professor_evidence_conflict_has_exact_candidates_question_and_urgent_recheck(env):
    change_due(env,None)
    env.service.run_once()
    env.now[0] += timedelta(minutes=1)
    with env.sessions() as session:
        assignment = session.get(Assignment,env.assignment_id)
        for external_id,hours,source_type,authority in (("professor-ann",20,"announcement",0.97),("professor-mail",8,"inbox_message",1.0)):
            attach_deadline_evidence(session,assignment,external_id=external_id,
                due_at=env.now[0]+timedelta(hours=hours),source_type=source_type,
                published_at=env.now[0]-timedelta(hours=1),authority=authority)
        session.commit()
    env.service.run_once()
    assert len(env.primary.calls)==1 and len(env.discord.calls)==1
    body = env.discord.calls[0]["message"]
    assert "Sources disagree" in body and "Tuesday, September 29 at 4:01 PM EDT" in body
    assert "Wednesday, September 30 at 4:01 AM EDT" in body
    assert "Share any extra context" in body and env.checks == [env.assignment_id]*2


def test_one_followup_freeform_reply_saved_without_canonical_change(env):
    change_due(env, None)
    env.service.run_once()
    with env.sessions() as session:
        event = AcademicUpdateEvent(event_key="new-risk", kind="information_needed", assignment_id=env.assignment_id,
            facts={"deadline":None}, question="What did the professor say? Any context helps.", observed_at=env.now[0])
        session.add(event)
        session.commit()
        key = event.id
    env.service.run_once()
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert [row.notification_kind for row in rows(env)] == ["academic_update","academic_followup"]
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert len(rows(env)) == 2
    env.service.remember_reply(key, "The professor said this is practice, 18 questions; I'll confirm the timing tomorrow.")
    with env.sessions() as session:
        assert session.get(AcademicUpdateEvent,key).answered_at is not None
        assert session.get(Assignment,env.assignment_id).canvas_due_at is None
        assert "18 questions" in session.scalar(select(AcademicNote)).body


def test_reply_before_followup_stops_followup_and_schema_preserves_audit(env):
    start_change(env)
    env.service.run_once()
    with env.sessions() as session:
        event = session.scalar(select(AcademicUpdateEvent).where(AcademicUpdateEvent.kind=="deadline_change"))
        event.question = "Please clarify the instructions."
        session.commit()
        key = event.id
    env.service.remember_reply(key, "Here is my context; keep deadlines unchanged.")
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert len(rows(env)) == 1
    create_schema(env.engine)
    assert len(rows(env)) == 1


def test_excerpt_is_plain_bounded_and_redacts_contacts_and_credentials():
    source = SourceRecord(raw_payload={"message":"<script>steal()</script><p>Study guide <b>updated</b></p> x@y.edu https://secret.test sk-12345678901234567890"})
    text = announcement_excerpt(source)
    assert "Study guide updated" in text and "steal" not in text
    assert "x@y.edu" not in text and "secret.test" not in text and "sk-" not in text and len(text)<=320


def test_real_fact_preview_is_explicit_audited_rechecked_and_never_followed_up(env):
    with env.sessions() as session:
        assignment = session.get(Assignment,env.assignment_id)
        event = AcademicUpdateEvent(event_key="owner-preview", kind="planning_review", assignment_id=assignment.id,
            facts={"deadline":assignment.canvas_due_at.replace(tzinfo=UTC).isoformat()},
            question="How does this fit around your shifts? Any context helps.", observed_at=env.now[0],status="preview")
        delivery = NotificationDelivery(dedup_key="owner-preview", notification_kind="academic_update_preview", provider="discord",
            rendered_title="Preview", rendered_body="Rebuilt from verified facts before delivery", priority=3,
            status="retry_scheduled", attempted_at=env.now[0])
        session.add_all([event,delivery])
        session.flush()
        event.discord_delivery_id = delivery.id
        session.add(NotificationMirrorContext(delivery_id=delivery.id,assignment_ids=[assignment.id],
            deadline_versions={str(assignment.id):event.facts["deadline"]}, expires_at=env.now[0]+timedelta(minutes=15),
            next_attempt_at=env.now[0],attempts=0))
        session.commit()
        key = delivery.id
    env.service._attempt(key)
    assert rows(env)[0].status == "sent" and env.checks == [env.assignment_id]
    assert "not a new professor announcement" in env.discord.calls[0]["message"]
    assert env.discord.calls[0]["title"] == "School update preview"
    env.now[0] += timedelta(hours=48)
    env.service.run_once()
    assert len(env.discord.calls)==1 and not env.primary.calls
