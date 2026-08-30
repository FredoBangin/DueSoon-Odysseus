from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from src.duesoon.api.app import create_app
from src.duesoon.assignments.effective import EffectiveAssignment
from src.duesoon.auth.passwords import hash_password
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import create_engine_from_settings, session_factory
from src.duesoon.persistence.models import Assignment, CalendarBusyBlock, Course
from src.duesoon.planning import PlanningService
from src.duesoon.planning.priority import EffortProjection, score_work_priority


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def effective(
    assignment_id: int,
    *,
    title: str,
    due_in: timedelta | None,
    points: float = 10,
    status: str = "not_submitted",
) -> EffectiveAssignment:
    due = NOW + due_in if due_in is not None else None
    return EffectiveAssignment(
        assignment_id=assignment_id,
        canvas_assignment_id=str(assignment_id),
        canvas_course_id="course-1",
        course_name="Course",
        title=title,
        external_url=None,
        canvas_due_at=due,
        effective_due_at=due,
        operational_due_at=due,
        deadline_status="resolved" if due else "unknown",
        deadline_confidence="high" if due else "low",
        deadline_source_summary="fixture",
        deadline_evidence_ids=(),
        previous_due_at=None,
        deadline_changed_at=None,
        deadline_change_hours=None,
        points_possible=points,
        submission_status=status,
        submitted_at=NOW if status == "submitted" else None,
    )


def effort(minutes: int, *, progress: int = 0) -> EffortProjection:
    remaining = round(minutes * (100 - progress) / 100)
    return EffortProjection(
        estimated_minutes=minutes,
        lower_minutes=round(minutes * 0.75),
        upper_minutes=round(minutes * 1.25),
        remaining_minutes=remaining,
        progress_percent=progress,
        confidence="medium",
        source="fixture",
        evidence_ids=(),
        assumptions=(),
    )


def test_large_distant_project_outranks_small_nearer_quiz_by_slack() -> None:
    project = effective(1, title="Capstone Project", due_in=timedelta(days=7), points=100)
    quiz = effective(2, title="Quiz 2", due_in=timedelta(days=2), points=10)
    items = (project, quiz)

    project_score = score_work_priority(
        project, items, effort(2700), NOW, course_value_percentile=1.0
    )
    quiz_score = score_work_priority(
        quiz, items, effort(60), NOW, course_value_percentile=0.5
    )

    assert project_score.total > quiz_score.total
    assert project_score.start_by_at is None
    assert project_score.slack_minutes is None
    assert project_score.usable_minutes_until_due is None
    assert project_score.workload_pressure_score > quiz_score.workload_pressure_score
    assert any("capacity" in value.casefold() for value in project_score.assumptions)
    assert project_score.config_version == "work-priority-v2"
    assert sum(project_score.factor_breakdown.values()) == project_score.total


def test_progress_reduces_remaining_effort_and_priority_without_changing_deadline() -> None:
    item = effective(1, title="Research Project", due_in=timedelta(days=3), points=100)
    untouched_due = item.operational_due_at

    unstarted = score_work_priority(item, (item,), effort(600), NOW)
    halfway = score_work_priority(item, (item,), effort(600, progress=50), NOW)

    assert halfway.remaining_effort_minutes == 300
    assert halfway.total < unstarted.total
    assert item.operational_due_at == untouched_due


def test_unknown_effort_is_visible_and_never_invented() -> None:
    item = effective(1, title="Unclassified work", due_in=timedelta(days=4))
    unknown = EffortProjection.unknown()

    result = score_work_priority(item, (item,), unknown, NOW)

    assert result.estimated_effort_minutes is None
    assert result.remaining_effort_minutes is None
    assert result.start_by_at is None
    assert result.slack_minutes is None
    assert result.confidence == "low"
    assert result.band == "MONITOR"
    assert "Effort is unknown" in result.reasons


def test_known_calendar_blocks_reduce_learned_usable_capacity() -> None:
    item = effective(1, title="Research Project", due_in=timedelta(days=2))

    open_schedule = score_work_priority(
        item, (item,), effort(180), NOW, usable_hours_per_day=4
    )
    work_shift = score_work_priority(
        item,
        (item,),
        effort(180),
        NOW,
        usable_hours_per_day=4,
        calendar_blocked_minutes=540,
    )

    assert work_shift.calendar_blocked_minutes == 540
    assert work_shift.usable_minutes_until_due < open_schedule.usable_minutes_until_due
    assert work_shift.slack_minutes < open_schedule.slack_minutes
    assert work_shift.workload_pressure_score > open_schedule.workload_pressure_score
    assert any("calendar" in reason.casefold() for reason in work_shift.reasons)


def test_calendar_blocks_remain_context_when_capacity_is_unknown() -> None:
    item = effective(1, title="Research Project", due_in=timedelta(days=2))

    result = score_work_priority(
        item,
        (item,),
        effort(480),
        NOW,
        calendar_blocked_minutes=540,
    )

    assert result.calendar_blocked_minutes == 540
    assert result.usable_minutes_until_due is None
    assert result.slack_minutes is None
    assert any("calendar" in reason.casefold() for reason in result.reasons)


def test_completed_work_never_ranks_active() -> None:
    item = effective(
        1,
        title="Submitted project",
        due_in=timedelta(hours=-2),
        status="submitted",
    )

    result = score_work_priority(item, (item,), effort(900), NOW)

    assert result.total == 0
    assert result.band == "MONITOR"
    assert result.reasons == ("Work is complete",)


def test_school_test_gets_exam_effort_prior(tmp_path: Path) -> None:
    client, engine = build(tmp_path)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="course-1", name="Course")
            assignment = Assignment(
                canvas_assignment_id="unit-test",
                course=course,
                canonical_title="Unit Test 1",
                canvas_due_at=NOW + timedelta(days=5),
                published=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add(assignment)
            session.commit()
            assignment_id = assignment.id

        value = PlanningService(session_factory(engine)).inspect(assignment_id)

        assert value["effort"]["estimated_minutes"] == 240
        assert value["effort"]["source"] == "assignment_type_prior"
    engine.dispose()


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'priority.db').as_posix()}",
        web_enabled=True,
        public_origin="https://due.test",
        owner_username="owner",
        owner_password_hash=hash_password("correct-password-123"),
    )
    engine = create_engine_from_settings(settings)
    client = TestClient(create_app(settings, engine=engine), base_url="https://due.test")
    return client, engine


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://due.test"},
        json={"username": "owner", "password": "correct-password-123"},
    )
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_briefing_orders_work_by_priority_and_owner_corrections_are_append_only(
    tmp_path: Path,
) -> None:
    client, engine = build(tmp_path)
    runtime_now = datetime.now(UTC)
    with client:
        with session_factory(engine)() as session:
            course = Course(canvas_course_id="course-1", name="Course")
            project = Assignment(
                canvas_assignment_id="project",
                course=course,
                canonical_title="Capstone Project",
                canvas_due_at=NOW + timedelta(days=7),
                points_possible=100,
                published=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            quiz = Assignment(
                canvas_assignment_id="quiz",
                course=course,
                canonical_title="Quiz 2",
                canvas_due_at=NOW + timedelta(days=2),
                points_possible=10,
                published=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add_all([project, quiz])
            session.add(
                CalendarBusyBlock(
                    source_system="google_calendar",
                    external_id_hash="a" * 64,
                    starts_at=runtime_now + timedelta(hours=12),
                    ends_at=runtime_now + timedelta(hours=20),
                    all_day=False,
                    active=True,
                    observed_at=runtime_now,
                )
            )
            session.commit()
            project_id = project.id
        headers = login(client)
        briefing = client.get("/api/v1/dashboard/briefing").json()

        assert briefing["upcoming"][0]["title"] == "Capstone Project"
        priority = briefing["upcoming"][0]["work_priority"]
        assert 0 <= priority["score"] <= 100
        assert priority["band"] in {"NOW", "NEXT", "LATER", "MONITOR"}
        assert priority["estimated_effort_minutes"] == 600
        assert priority["confidence"] == "low"
        assert priority["calendar_blocked_minutes"] == 480
        original_due = briefing["upcoming"][0]["due_at"]

        first = client.post(
            f"/api/v1/dashboard/assignments/{project_id}/planning",
            headers=headers,
            json={"estimated_minutes": 300, "percent_complete": 25, "note": "Owner estimate"},
        )
        second = client.post(
            f"/api/v1/dashboard/assignments/{project_id}/planning",
            headers=headers,
            json={"estimated_minutes": 240},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["effort"]["estimated_minutes"] == 240
        assert second.json()["effort_history_count"] == 2
        assert second.json()["progress_history_count"] == 1
        refreshed = client.get("/api/v1/dashboard/briefing").json()
        item = next(value for value in refreshed["upcoming"] if value["id"] == project_id)
        assert item["due_at"] == original_due
        assert item["work_priority"]["estimated_effort_minutes"] == 240
        assert item["work_priority"]["progress_percent"] == 25
    engine.dispose()
