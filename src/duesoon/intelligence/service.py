"""Owner-controlled evidence inspection and deadline confirmation service."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.assignments.effective import EffectiveAssignment, project_canvas_assignment
from src.duesoon.intelligence.evidence import deadline_candidate_from_evidence
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentEvidence,
    Claim,
    SourceRecord,
)


@dataclass(frozen=True)
class SafeEvidenceItem:
    evidence_id: str
    source_system: str
    source_type: str
    claim_type: str
    claimed_due_at: datetime | None
    source_published_at: datetime | None
    precision: str
    validation_status: str
    disposition: str
    authority_score: float
    course_match_score: float
    assignment_match_score: float
    explicitness_score: float
    extraction_reliability: float
    owner_confirmed: bool
    source_current: bool
    supports_current_resolution: bool
    summary: str


@dataclass(frozen=True)
class EvidenceInspection:
    assignment_id: int
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    deadline_status: str
    deadline_confidence: str
    deadline_evidence_ids: tuple[str, ...]
    due_at_precision: str
    resolution_explanation: str
    conflicting_due_at: tuple[datetime, ...]
    items: tuple[SafeEvidenceItem, ...]


@dataclass(frozen=True)
class ConfirmationResult:
    created: bool
    evidence_id: str
    inspection: EvidenceInspection


def assignment_load_options():
    """Relationships required by Effective Assignment projection."""

    return (
        selectinload(Assignment.course),
        selectinload(Assignment.submission),
        selectinload(Assignment.snapshots),
        selectinload(Assignment.evidence)
        .selectinload(AssignmentEvidence.claim)
        .selectinload(Claim.source_record),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("deadline must include an explicit timezone offset")
    return value.astimezone(UTC)


class EvidenceInspectionService:
    """Apply evidence lifecycle policy outside HTTP route handlers."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    def inspect(self, assignment_id: int) -> EvidenceInspection:
        with self._sessions() as session:
            assignment = self._assignment(session, assignment_id)
            effective = project_canvas_assignment(assignment)
            return self._inspection(assignment, effective)

    def confirm_deadline(self, assignment_id: int, due_at: datetime) -> ConfirmationResult:
        confirmed_due = _utc(due_at)
        now = _utc(self._clock())
        fingerprint = hashlib.sha256(
            (
                f"owner-confirmation-v1:{assignment_id}:"
                f"{confirmed_due.isoformat()}"
            ).encode("utf-8")
        ).hexdigest()
        external_id = f"assignment-{assignment_id}-{fingerprint[:24]}"

        created = False
        with self._sessions() as session:
            assignment = self._assignment(session, assignment_id)
            existing = self._confirmed_evidence(session, assignment_id, external_id)
            if existing is None:
                before = project_canvas_assignment(assignment)
                source = SourceRecord(
                    source_system="owner",
                    source_type="confirmation",
                    external_id=external_id,
                    course_id=assignment.course_id,
                    source_published_at=now,
                    observed_at=now,
                    content_hash=fingerprint,
                    version=1,
                    raw_payload={
                        "event": "owner_deadline_confirmation",
                        "assignment_id": assignment.id,
                        "course_id": assignment.course_id,
                    },
                    ingestion_status="validated",
                    parser_version="owner-confirmation-v1",
                )
                claim = Claim(
                    source_record=source,
                    claim_type="deadline_is",
                    course_hint=assignment.course.canvas_course_id,
                    assignment_hint=assignment.canonical_title,
                    normalized_value={
                        "due_at": confirmed_due.isoformat(),
                        "precision": "exact_datetime",
                    },
                    source_locator="owner confirmation",
                    author_identity="owner",
                    author_role="owner",
                    source_published_at=now,
                    source_observed_at=now,
                    extraction_method="owner_confirmation",
                    extractor_version="owner-confirmation-v1",
                    extraction_confidence=1.0,
                    validation_status="validated",
                    claim_fingerprint=fingerprint,
                )
                existing = AssignmentEvidence(
                    assignment=assignment,
                    claim=claim,
                    course_match_score=1.0,
                    assignment_match_score=1.0,
                    authority_score=1.0,
                    explicitness_score=1.0,
                    precision="exact_datetime",
                    owner_confirmed=True,
                    author_verified=True,
                    source_current=True,
                    recency_features={"source_published_at": now.isoformat()},
                    corroboration_features={"kind": "owner_confirmation"},
                    supersedes_evidence_ids=list(before.deadline_evidence_ids),
                    disposition="admitted",
                    explanation=(
                        "Owner confirmed an exact timezone-aware deadline scoped to this "
                        "assignment and course."
                    ),
                )
                session.add(existing)
                try:
                    session.commit()
                    created = True
                except IntegrityError:
                    session.rollback()
                    existing = self._confirmed_evidence(
                        session, assignment_id, external_id
                    )
                    if existing is None:
                        raise
            evidence_id = self._public_evidence_id(existing)

        inspection = self.inspect(assignment_id)
        return ConfirmationResult(created, evidence_id, inspection)

    @staticmethod
    def _assignment(session: Session, assignment_id: int) -> Assignment:
        assignment = session.scalar(
            select(Assignment)
            .where(Assignment.id == assignment_id)
            .options(*assignment_load_options())
        )
        if assignment is None:
            raise LookupError("assignment not found")
        return assignment

    @staticmethod
    def _confirmed_evidence(
        session: Session,
        assignment_id: int,
        external_id: str,
    ) -> AssignmentEvidence | None:
        return session.scalar(
            select(AssignmentEvidence)
            .join(AssignmentEvidence.claim)
            .join(Claim.source_record)
            .where(
                AssignmentEvidence.assignment_id == assignment_id,
                SourceRecord.source_system == "owner",
                SourceRecord.source_type == "confirmation",
                SourceRecord.external_id == external_id,
            )
            .options(
                selectinload(AssignmentEvidence.claim).selectinload(Claim.source_record)
            )
        )

    def _inspection(
        self,
        assignment: Assignment,
        effective: EffectiveAssignment,
    ) -> EvidenceInspection:
        selected = set(effective.deadline_evidence_ids)
        items = [self._canvas_item(assignment, selected)] if assignment.canvas_due_at else []
        items.extend(self._persisted_item(item, selected) for item in assignment.evidence)
        items.sort(
            key=lambda item: (
                self._sortable_timestamp(item.source_published_at),
                item.evidence_id,
            ),
            reverse=True,
        )
        return EvidenceInspection(
            assignment_id=assignment.id,
            effective_due_at=effective.effective_due_at,
            operational_due_at=effective.operational_due_at,
            deadline_status=effective.deadline_status,
            deadline_confidence=effective.deadline_confidence,
            deadline_evidence_ids=effective.deadline_evidence_ids,
            due_at_precision=effective.due_at_precision,
            resolution_explanation=effective.deadline_resolution_explanation,
            conflicting_due_at=effective.conflicting_due_at,
            items=tuple(items),
        )

    @staticmethod
    def _sortable_timestamp(value: datetime | None) -> float:
        if value is None:
            return float("-inf")
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).timestamp()

    @staticmethod
    def _public_evidence_id(evidence: AssignmentEvidence) -> str:
        return f"assignment-evidence:{evidence.id}:claim:{evidence.claim_id}"

    def _persisted_item(
        self,
        evidence: AssignmentEvidence,
        selected: set[str],
    ) -> SafeEvidenceItem:
        claim = evidence.claim
        source = claim.source_record
        candidate = deadline_candidate_from_evidence(evidence)
        evidence_id = self._public_evidence_id(evidence)
        source_label = f"{source.source_system} {source.source_type}".replace("_", " ")
        summary = (
            "Owner-confirmed exact deadline."
            if evidence.owner_confirmed
            else f"{claim.claim_type.replace('_', ' ').capitalize()} from {source_label}."
        )
        return SafeEvidenceItem(
            evidence_id=evidence_id,
            source_system=source.source_system,
            source_type=source.source_type,
            claim_type=claim.claim_type,
            claimed_due_at=candidate.due_at if candidate is not None else None,
            source_published_at=claim.source_published_at or source.source_published_at,
            precision=evidence.precision,
            validation_status=claim.validation_status,
            disposition=evidence.disposition,
            authority_score=evidence.authority_score,
            course_match_score=evidence.course_match_score,
            assignment_match_score=evidence.assignment_match_score,
            explicitness_score=evidence.explicitness_score,
            extraction_reliability=claim.extraction_confidence,
            owner_confirmed=evidence.owner_confirmed,
            source_current=evidence.source_current,
            supports_current_resolution=evidence_id in selected,
            summary=summary,
        )

    @staticmethod
    def _canvas_item(
        assignment: Assignment,
        selected: set[str],
    ) -> SafeEvidenceItem:
        evidence_id = (
            f"canvas-assignment:{assignment.canvas_assignment_id}:current"
        )
        return SafeEvidenceItem(
            evidence_id=evidence_id,
            source_system="canvas",
            source_type="assignment",
            claim_type="deadline_is",
            claimed_due_at=assignment.canvas_due_at,
            source_published_at=assignment.canvas_updated_at or assignment.updated_at,
            precision="exact_datetime",
            validation_status="validated",
            disposition="admitted",
            authority_score=0.95,
            course_match_score=1.0,
            assignment_match_score=1.0,
            explicitness_score=1.0,
            extraction_reliability=1.0,
            owner_confirmed=False,
            source_current=True,
            supports_current_resolution=evidence_id in selected,
            summary="Current structured Canvas assignment deadline.",
        )
