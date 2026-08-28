"""Strict conversion from persisted evidence into resolver candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol

from src.duesoon.intelligence.deadline_resolver import DeadlineCandidate


DEADLINE_CLAIM_TYPES = frozenset(
    {
        "deadline_is",
        "deadline_changed_to",
        "deadline_extended_to",
        "deadline_moved_earlier_to",
    }
)
SUPPORTED_PRECISIONS = frozenset(
    {"exact_datetime", "date_only", "relative", "unknown"}
)


class SourceRecordLike(Protocol):
    source_system: str
    source_type: str
    external_id: str
    source_published_at: datetime | None


class ClaimLike(Protocol):
    id: int
    claim_type: str
    normalized_value: dict[str, object]
    source_published_at: datetime | None
    extraction_confidence: float
    validation_status: str
    source_record: SourceRecordLike


class AssignmentEvidenceLike(Protocol):
    id: int
    disposition: str
    course_match_score: float
    assignment_match_score: float
    authority_score: float
    explicitness_score: float
    precision: str
    supersedes_evidence_ids: list[str]
    owner_confirmed: bool
    author_verified: bool
    source_current: bool
    claim: ClaimLike


_SOURCE_KIND: dict[tuple[str, str], str] = {
    ("canvas", "assignment"): "canvas_assignment",
    ("canvas", "inbox_message"): "canvas_inbox_correction",
    ("canvas", "conversation_message"): "canvas_inbox_correction",
    ("canvas", "announcement"): "course_announcement",
    ("canvas", "page"): "assignment_instructions",
    ("canvas", "file"): "instructor_document",
    ("canvas", "module"): "canvas_module",
    ("canvas", "module_item"): "canvas_module",
    ("gmail", "message"): "professor_email_correction",
    ("email", "message"): "professor_email_correction",
    ("document", "syllabus"): "syllabus",
    ("document", "course_document"): "instructor_document",
    ("owner", "confirmation"): "student_note",
}


def _parse_aware_iso(value: object) -> datetime | None:
    """Parse ISO 8601 only when date, time, and timezone are explicit."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _source_kind(source: SourceRecordLike) -> str:
    key = (source.source_system.casefold(), source.source_type.casefold())
    return _SOURCE_KIND.get(key, f"{key[0]}:{key[1]}")


def deadline_candidate_from_evidence(
    evidence: AssignmentEvidenceLike,
) -> DeadlineCandidate | None:
    """Return candidate only for admitted, validated, safe deadline evidence.

    Date-only claims may carry an explicitly normalized timestamp for ordering,
    but retain ``date_only`` precision so resolver cannot schedule checkpoints.
    Naive or malformed timestamps are rejected; no time or timezone is invented.
    """

    claim = evidence.claim
    if evidence.disposition != "admitted":
        return None
    if claim.validation_status != "validated":
        return None
    if claim.claim_type not in DEADLINE_CLAIM_TYPES:
        return None
    if not isinstance(claim.normalized_value, dict):
        return None

    due_at = _parse_aware_iso(claim.normalized_value.get("due_at"))
    if due_at is None:
        return None
    precision = claim.normalized_value.get("precision", evidence.precision)
    if not isinstance(precision, str) or precision not in SUPPORTED_PRECISIONS:
        return None
    if evidence.precision not in SUPPORTED_PRECISIONS or precision != evidence.precision:
        return None
    supersedes = evidence.supersedes_evidence_ids or []
    if not isinstance(supersedes, list) or not all(
        isinstance(item, str) and item for item in supersedes
    ):
        return None

    source = claim.source_record
    published_at = claim.source_published_at or source.source_published_at
    try:
        return DeadlineCandidate(
            evidence_id=f"assignment-evidence:{evidence.id}:claim:{claim.id}",
            due_at=due_at,
            source_kind=_source_kind(source),
            published_at=published_at,
            authority=evidence.authority_score,
            course_match=evidence.course_match_score,
            assignment_match=evidence.assignment_match_score,
            explicitness=evidence.explicitness_score,
            precision=precision,
            explicit_correction=claim.claim_type != "deadline_is",
            user_confirmed=bool(evidence.owner_confirmed),
            author_verified=bool(evidence.author_verified),
            source_current=bool(evidence.source_current),
            extraction_reliability=claim.extraction_confidence,
            supersedes_evidence_ids=tuple(supersedes),
            independence_key=(
                f"{source.source_system}:{source.source_type}:{source.external_id}"
            ),
        )
    except (TypeError, ValueError):
        return None


def deadline_candidates_from_evidence(
    evidence_records: Iterable[AssignmentEvidenceLike],
) -> tuple[DeadlineCandidate, ...]:
    """Convert evidence records without mutating ORM or resolver state."""

    candidates = []
    for evidence in evidence_records:
        candidate = deadline_candidate_from_evidence(evidence)
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)
