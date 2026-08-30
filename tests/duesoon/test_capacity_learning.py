from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.dashboard.briefing import BriefingService
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEffortEstimate,
    AssignmentProgressObservation,
    Course,
    Submission,
)
from src.duesoon.planning import PlanningService


NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def build(tmp_path: Path):
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'capacity.db').as_posix()}",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    return engine, sessions, PlanningService(sessions)


def add_outcome(session, course, index: int, effort: int, days: int) -> None:
    submitted_at = NOW - timedelta(days=index)
    assignment = Assignment(
        canvas_assignment_id=f"done-{index}",
        course=course,
        canonical_title=f"Completed work {index}",
        canvas_due_at=submitted_at,
        published=True,
        first_seen_at=submitted_at - timedelta(days=days + 1),
        last_seen_at=submitted_at,
    )
    session.add(assignment)
    session.flush()
    session.add_all(
        [
            Submission(
                assignment=assignment,
                normalized_status="submitted",
                submitted_at=submitted_at,
                missing=False,
                late=False,
                observed_at=submitted_at,
                raw_payload={},
            ),
            AssignmentEffortEstimate(
                assignment_id=assignment.id,
                estimated_minutes=effort,
                lower_minutes=effort,
                upper_minutes=effort,
                confidence="high",
                source_kind="owner_confirmed",
                owner_confirmed=True,
                created_at=submitted_at - timedelta(days=days),
            ),
            AssignmentProgressObservation(
                assignment_id=assignment.id,
                percent_complete=0,
                source_kind="owner",
                created_at=submitted_at - timedelta(days=days),
            ),
        ]
    )


def test_capacity_stays_unknown_until_three_confirmed_outcomes(tmp_path: Path) -> None:
    engine, sessions, planning = build(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="course", name="Course")
            session.add(course)
            session.flush()
            add_outcome(session, course, 1, 180, 1)
            add_outcome(session, course, 2, 240, 2)
            session.commit()

        result = planning.capacity_learning()

        assert result["status"] == "insufficient_evidence"
        assert result["sample_count"] == 2
        assert result["learned_minutes_per_day"] is None
        assert result["affects_deadlines"] is False
        assert result["affects_reminders"] is False
    finally:
        engine.dispose()


def test_capacity_learns_median_pace_from_confirmed_effort_and_progress(
    tmp_path: Path,
) -> None:
    engine, sessions, planning = build(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="course", name="Course")
            session.add(course)
            session.flush()
            add_outcome(session, course, 1, 180, 1)
            add_outcome(session, course, 2, 240, 2)
            add_outcome(session, course, 3, 300, 2)
            session.commit()

        result = planning.capacity_learning()

        assert result["status"] == "learned"
        assert result["sample_count"] == 3
        assert result["learned_minutes_per_day"] == 150
        assert result["confidence"] == "medium"
        assert len(result["evidence_ids"]) == 3
        assert result["method"] == "median_confirmed_remaining_effort_per_day"
    finally:
        engine.dispose()


def test_completed_assignment_without_effort_becomes_learning_question(
    tmp_path: Path,
) -> None:
    engine, sessions, planning = build(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="course", name="Course")
            assignment = Assignment(
                canvas_assignment_id="needs-effort",
                course=course,
                canonical_title="Midterm Test",
                canvas_due_at=NOW,
                published=True,
                first_seen_at=NOW - timedelta(days=3),
                last_seen_at=NOW,
            )
            session.add(assignment)
            session.flush()
            session.add(
                Submission(
                    assignment=assignment,
                    normalized_status="submitted",
                    submitted_at=NOW,
                    missing=False,
                    late=False,
                    observed_at=NOW,
                    raw_payload={},
                )
            )
            session.commit()

        questions = planning.learning_questions()

        assert questions == [
            {
                "assignment_id": assignment.id,
                "title": "Midterm Test",
                "course_name": "Course",
                "prompt": "About how many minutes did Midterm Test take?",
            }
        ]
    finally:
        engine.dispose()


def test_briefing_uses_learned_pace_for_start_by_and_exposes_learning_state(
    tmp_path: Path,
) -> None:
    engine, sessions, planning = build(tmp_path)
    try:
        with sessions() as session:
            course = Course(canvas_course_id="course", name="Course")
            session.add(course)
            session.flush()
            add_outcome(session, course, 1, 180, 1)
            add_outcome(session, course, 2, 240, 2)
            add_outcome(session, course, 3, 300, 2)
            active = Assignment(
                canvas_assignment_id="active-project",
                course=course,
                canonical_title="Capstone Project",
                canvas_due_at=NOW + timedelta(days=5),
                points_possible=100,
                published=True,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add(active)
            session.commit()

        settings = DueSoonSettings(
            _env_file=None,
            environment="test",
            database_url=f"sqlite:///{(tmp_path / 'capacity.db').as_posix()}",
        )
        snapshot = BriefingService(settings, sessions, planning).snapshot(now=NOW)
        project = next(item for item in snapshot["upcoming"] if item["title"] == "Capstone Project")

        assert snapshot["capacity_learning"]["learned_minutes_per_day"] == 150
        assert project["work_priority"]["start_by_at"] is not None
        assert project["work_priority"]["confidence"] == "medium"
        assert any(
            "learned" in assumption.casefold()
            for assumption in project["work_priority"]["assumptions"]
        )
    finally:
        engine.dispose()
