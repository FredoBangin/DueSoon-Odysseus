from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import Assignment, AssignmentSnapshot, Course, SourceRecord


@pytest.fixture
def database():
    settings = DueSoonSettings(_env_file=None, database_url="sqlite:///:memory:")
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    try:
        yield engine, session_factory(engine)
    finally:
        engine.dispose()


def test_schema_contains_canvas_core_tables(database) -> None:
    engine, _ = database

    assert set(engine.dialect.get_table_names(engine.connect())) >= {
        "courses",
        "source_records",
        "assignments",
        "assignment_completion_observations",
        "assignment_snapshots",
        "submissions",
        "sync_runs",
    }


def test_canvas_course_identity_is_unique(database) -> None:
    _, sessions = database

    with sessions() as session:
        session.add_all(
            [
                Course(canvas_course_id="42", name="Security"),
                Course(canvas_course_id="42", name="Security duplicate"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_source_record_version_is_deduplicated(database) -> None:
    _, sessions = database
    observed = datetime.now(UTC)

    with sessions() as session:
        session.add_all(
            [
                SourceRecord(
                    source_system="canvas",
                    source_type="assignment",
                    external_id="99",
                    content_hash="same-hash",
                    observed_at=observed,
                    raw_payload={"id": 99},
                ),
                SourceRecord(
                    source_system="canvas",
                    source_type="assignment",
                    external_id="99",
                    content_hash="same-hash",
                    observed_at=observed,
                    raw_payload={"id": 99},
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_assignment_snapshot_content_is_deduplicated(database) -> None:
    _, sessions = database
    observed = datetime.now(UTC)

    with sessions() as session:
        course = Course(canvas_course_id="42", name="Security")
        source = SourceRecord(
            source_system="canvas",
            source_type="assignment",
            external_id="99",
            content_hash="source-hash",
            observed_at=observed,
            raw_payload={"id": 99},
        )
        assignment = Assignment(
            canvas_assignment_id="99",
            course=course,
            canonical_title="Lab 1",
            first_seen_at=observed,
            last_seen_at=observed,
        )
        session.add_all([course, source, assignment])
        session.flush()
        session.add_all(
            [
                AssignmentSnapshot(
                    assignment_id=assignment.id,
                    source_record_id=source.id,
                    content_hash="same-hash",
                    normalized_payload={"title": "Lab 1"},
                    observed_at=observed,
                ),
                AssignmentSnapshot(
                    assignment_id=assignment.id,
                    source_record_id=source.id,
                    content_hash="same-hash",
                    normalized_payload={"title": "Lab 1"},
                    observed_at=observed,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
