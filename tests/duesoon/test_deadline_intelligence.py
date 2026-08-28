"""Focused tests for deterministic deadline evidence and entity matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.duesoon.assignments.effective import project_canvas_assignment
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.intelligence.deadline_resolver import (
    DeadlineCandidate,
    resolve_deadline,
    source_authority,
)
from src.duesoon.intelligence.matcher import (
    AssignmentHint,
    AssignmentReference,
    match_assignment,
    normalize_assignment_title,
)
from src.duesoon.intelligence.evidence import deadline_candidate_from_evidence
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    AssignmentSnapshot,
    Claim,
    Course,
    SourceRecord,
)


PUBLISHED = datetime(2026, 8, 20, 12, tzinfo=UTC)
OLD_DUE = datetime(2026, 9, 4, 23, 59, tzinfo=UTC)
NEW_DUE = datetime(2026, 9, 6, 23, 59, tzinfo=UTC)


def candidate(
    evidence_id: str,
    due_at: datetime,
    *,
    source_kind: str = "canvas_assignment",
    authority: float | None = None,
    published_at: datetime | None = PUBLISHED,
    **features: object,
) -> DeadlineCandidate:
    return DeadlineCandidate(
        evidence_id=evidence_id,
        due_at=due_at,
        source_kind=source_kind,
        published_at=published_at,
        authority=source_authority(source_kind) if authority is None else authority,
        **features,
    )


def memory_database():
    settings = DueSoonSettings(_env_file=None, database_url="sqlite:///:memory:")
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    return engine, session_factory(engine)


def evidence_stub(
    *,
    disposition: str = "admitted",
    validation_status: str = "validated",
    claim_type: str = "deadline_extended_to",
    due_at: object = NEW_DUE.isoformat(),
    precision: str = "exact_datetime",
):
    source = SimpleNamespace(
        source_system="canvas",
        source_type="inbox_message",
        external_id="message-7",
        source_published_at=PUBLISHED,
    )
    claim = SimpleNamespace(
        id=7,
        claim_type=claim_type,
        normalized_value={"due_at": due_at, "precision": precision},
        source_published_at=PUBLISHED + timedelta(hours=1),
        extraction_confidence=0.91,
        validation_status=validation_status,
        source_record=source,
    )
    return SimpleNamespace(
        id=3,
        disposition=disposition,
        course_match_score=0.99,
        assignment_match_score=0.97,
        authority_score=1.0,
        explicitness_score=0.96,
        precision=precision,
        supersedes_evidence_ids=["canvas:99"],
        owner_confirmed=True,
        author_verified=True,
        source_current=True,
        claim=claim,
    )


def test_source_authority_requires_known_explicit_policy() -> None:
    assert source_authority("canvas_assignment") == 0.95
    assert source_authority("professor_email_correction") == 1.0
    with pytest.raises(ValueError, match="unknown deadline source kind"):
        source_authority("model_guess")


def test_persisted_evidence_conversion_preserves_validated_resolution_features() -> None:
    converted = deadline_candidate_from_evidence(evidence_stub())

    assert converted is not None
    assert converted.evidence_id == "assignment-evidence:3:claim:7"
    assert converted.due_at == NEW_DUE
    assert converted.source_kind == "canvas_inbox_correction"
    assert converted.published_at == PUBLISHED + timedelta(hours=1)
    assert converted.authority == 1.0
    assert converted.course_match == 0.99
    assert converted.assignment_match == 0.97
    assert converted.explicitness == 0.96
    assert converted.extraction_reliability == 0.91
    assert converted.explicit_correction is True
    assert converted.user_confirmed is True
    assert converted.supersedes_evidence_ids == ("canvas:99",)
    assert converted.independence_key == "canvas:inbox_message:message-7"


@pytest.mark.parametrize(
    "evidence",
    [
        evidence_stub(disposition="provisional"),
        evidence_stub(validation_status="rejected"),
        evidence_stub(claim_type="workload_hint"),
        evidence_stub(due_at="not-a-date"),
        evidence_stub(due_at="2026-09-06T23:59:00"),
    ],
)
def test_non_admitted_malformed_or_unsupported_evidence_is_rejected(evidence) -> None:
    assert deadline_candidate_from_evidence(evidence) is None


def test_date_only_evidence_cannot_create_operational_schedule() -> None:
    converted = deadline_candidate_from_evidence(
        evidence_stub(precision="date_only")
    )

    assert converted is not None
    result = resolve_deadline([converted])
    assert result.status == "provisional"
    assert result.operational_due_at is None


def test_canvas_deadline_resolves_with_auditable_assessment() -> None:
    result = resolve_deadline([candidate("canvas:99", OLD_DUE)])

    assert result.status == "resolved"
    assert result.confidence == "high"
    assert result.effective_due_at == OLD_DUE
    assert result.operational_due_at == OLD_DUE
    assert result.evidence_ids == ("canvas:99",)
    assert result.assessments[0].admissible is True
    assert "Best corroborated" in result.explanation


def test_imprecise_deadline_stays_provisional_and_cannot_schedule() -> None:
    result = resolve_deadline(
        [candidate("syllabus:page-2", OLD_DUE, source_kind="syllabus", precision="date_only")]
    )

    assert result.status == "provisional"
    assert result.effective_due_at == OLD_DUE
    assert result.operational_due_at is None
    assert result.precision == "date_only"
    assert "checkpoint reminders are withheld" in result.explanation


def test_low_assignment_match_is_retained_but_not_admitted() -> None:
    result = resolve_deadline(
        [candidate("inbox:ambiguous", OLD_DUE, assignment_match=0.64)]
    )

    assert result.status == "unknown"
    assert result.evidence_ids == ()
    assert result.assessments[0].admissible is False
    assert "assignment match is below 0.65" in result.assessments[0].reason


def test_newer_explicit_verified_correction_supersedes_old_canvas_value() -> None:
    result = resolve_deadline(
        [
            candidate("canvas:old", OLD_DUE),
            candidate(
                "inbox:extension",
                NEW_DUE,
                source_kind="canvas_inbox_correction",
                published_at=PUBLISHED + timedelta(days=3),
                explicit_correction=True,
                supersedes_evidence_ids=("canvas:old",),
            ),
        ]
    )

    assert result.status == "resolved"
    assert result.effective_due_at == NEW_DUE
    assert result.operational_due_at == NEW_DUE
    assert result.evidence_ids == ("inbox:extension",)
    assert "supersedes older" in result.explanation


def test_unverified_correction_cannot_silently_override_canvas() -> None:
    result = resolve_deadline(
        [
            candidate("canvas", OLD_DUE),
            candidate(
                "email-unverified",
                NEW_DUE,
                source_kind="professor_email_correction",
                published_at=PUBLISHED + timedelta(days=1),
                explicit_correction=True,
                author_verified=False,
            ),
        ]
    )

    assert result.status == "conflicted"
    assert result.operational_due_at == OLD_DUE
    assert set(result.conflicting_due_at) == {OLD_DUE, NEW_DUE}


def test_credible_unresolved_conflict_uses_earliest_protective_deadline() -> None:
    result = resolve_deadline(
        [
            candidate("announcement", NEW_DUE, source_kind="course_announcement"),
            candidate("canvas", OLD_DUE),
        ]
    )

    assert result.status == "conflicted"
    assert result.confidence == "medium"
    assert result.operational_due_at == OLD_DUE
    assert result.effective_due_at in {OLD_DUE, NEW_DUE}
    assert set(result.evidence_ids) == {"announcement", "canvas"}
    assert "protective scheduling" in result.explanation


def test_owner_confirmation_wins_but_preserves_other_assessments() -> None:
    result = resolve_deadline(
        [
            candidate("canvas", OLD_DUE),
            candidate("owner", NEW_DUE, source_kind="student_note", user_confirmed=True),
        ]
    )

    assert result.effective_due_at == NEW_DUE
    assert result.evidence_ids == ("owner",)
    assert {item.evidence_id for item in result.assessments} == {"canvas", "owner"}


def test_assignment_matching_is_course_scoped_and_prefers_exact_id() -> None:
    references = [
        AssignmentReference(1, 10, "Network Security Lab 4", canvas_assignment_id="99"),
        AssignmentReference(2, 20, "Network Security Lab 4", canvas_assignment_id="99"),
    ]

    result = match_assignment(
        AssignmentHint(course_id=10, canvas_assignment_id="99"),
        references,
    )

    assert result.assignment_id == 1
    assert result.score == 1.0
    assert result.confidence == "high"
    assert match_assignment(AssignmentHint(course_id=None, assignment_hint="Lab 4"), references).assignment_id is None


def test_course_alias_and_written_number_match_deterministically() -> None:
    assert normalize_assignment_title("Module Four: Lab") == "module 4 lab"
    references = [
        AssignmentReference(
            1,
            10,
            "Network Security Lab #4",
            aliases=("Module 4 Lab",),
            assignment_type="lab",
        ),
        AssignmentReference(2, 10, "Network Security Lab #5", aliases=("Module 5 Lab",)),
    ]

    result = match_assignment(
        AssignmentHint(course_id=10, assignment_hint="Module Four Lab", assignment_type="lab"),
        references,
    )

    assert result.assignment_id == 1
    assert result.confidence == "high"
    assert "assignment number agrees" in result.reasons


def test_ambiguous_same_course_titles_remain_unresolved() -> None:
    result = match_assignment(
        AssignmentHint(course_id=10, assignment_hint="Final paper"),
        [
            AssignmentReference(1, 10, "Final paper"),
            AssignmentReference(2, 10, "Final paper"),
        ],
    )

    assert result.assignment_id is None
    assert result.disposition == "ambiguous"
    assert len(result.alternatives) == 2


def test_claim_and_assignment_evidence_persist_provenance_and_deduplicate() -> None:
    engine, sessions = memory_database()
    try:
        with sessions() as session:
            course = Course(canvas_course_id="42", name="Network Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Lab 4",
                first_seen_at=PUBLISHED,
                last_seen_at=PUBLISHED,
            )
            source = SourceRecord(
                source_system="canvas",
                source_type="inbox_message",
                external_id="message-7",
                content_hash="source-hash",
                observed_at=PUBLISHED,
                source_published_at=PUBLISHED,
                raw_payload={"redacted_fixture": True},
            )
            claim = Claim(
                source_record=source,
                claim_type="deadline_extended_to",
                course_hint="42",
                assignment_hint="Lab 4",
                normalized_value={"due_at": NEW_DUE.isoformat(), "precision": "exact_datetime"},
                source_locator="message body, sentence 2",
                author_role="instructor",
                source_published_at=PUBLISHED,
                source_observed_at=PUBLISHED,
                extraction_method="deterministic_fixture",
                extractor_version="claims-v1",
                extraction_confidence=0.95,
                validation_status="validated",
                claim_fingerprint="claim-hash",
            )
            link = AssignmentEvidence(
                assignment=assignment,
                claim=claim,
                course_match_score=1.0,
                assignment_match_score=0.97,
                authority_score=1.0,
                explicitness_score=1.0,
                precision="exact_datetime",
                recency_features={"published_at": PUBLISHED.isoformat()},
                corroboration_features={"independent_sources": 1},
                supersedes_evidence_ids=["canvas:99"],
                disposition="admitted",
                explanation="Verified instructor extension matches Lab 4 in course 42.",
            )
            session.add_all([course, assignment, source, claim, link])
            session.commit()

            stored = session.scalar(select(AssignmentEvidence))
            assert stored is not None
            assert stored.claim.source_record.external_id == "message-7"
            assert stored.assignment.canvas_assignment_id == "99"
            assert stored.explanation.startswith("Verified instructor extension")

            session.add(
                Claim(
                    source_record=source,
                    claim_type="deadline_extended_to",
                    normalized_value={"due_at": NEW_DUE.isoformat()},
                    source_observed_at=PUBLISHED,
                    extraction_method="deterministic_fixture",
                    extractor_version="claims-v1",
                    extraction_confidence=0.95,
                    validation_status="validated",
                    claim_fingerprint="claim-hash",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_effective_projection_uses_resolver_and_retains_deadline_history() -> None:
    engine, sessions = memory_database()
    try:
        with sessions() as session:
            course = Course(canvas_course_id="42", name="Network Security")
            assignment = Assignment(
                canvas_assignment_id="99",
                course=course,
                canonical_title="Lab 4",
                canvas_due_at=OLD_DUE,
                canvas_updated_at=PUBLISHED,
                first_seen_at=PUBLISHED,
                last_seen_at=PUBLISHED,
            )
            source = SourceRecord(
                source_system="canvas",
                source_type="assignment",
                external_id="99",
                content_hash="assignment-hash",
                observed_at=PUBLISHED,
                raw_payload={"id": 99},
            )
            session.add_all([course, assignment, source])
            session.flush()
            assignment.snapshots.extend(
                [
                    AssignmentSnapshot(
                        source_record_id=source.id,
                        content_hash="old",
                        normalized_payload={"due_at": NEW_DUE.isoformat()},
                        due_at=NEW_DUE,
                        observed_at=PUBLISHED - timedelta(days=1),
                    ),
                    AssignmentSnapshot(
                        source_record_id=source.id,
                        content_hash="new",
                        normalized_payload={"due_at": OLD_DUE.isoformat()},
                        due_at=OLD_DUE,
                        observed_at=PUBLISHED,
                    ),
                ]
            )
            session.commit()

            extension = candidate(
                "inbox:extension",
                NEW_DUE,
                source_kind="canvas_inbox_correction",
                published_at=PUBLISHED + timedelta(days=1),
                explicit_correction=True,
            )
            effective = project_canvas_assignment(assignment, [extension])

            assert effective.canvas_due_at is not None
            assert effective.canvas_due_at.replace(tzinfo=UTC) == OLD_DUE
            assert effective.effective_due_at == NEW_DUE
            assert effective.operational_due_at == NEW_DUE
            assert effective.deadline_evidence_ids == ("inbox:extension",)
            assert effective.previous_due_at is not None
            assert effective.previous_due_at.replace(tzinfo=UTC) == NEW_DUE
            assert effective.deadline_change_hours == 48.0
            assert "supersedes older" in effective.deadline_resolution_explanation
    finally:
        engine.dispose()
