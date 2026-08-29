"""Sanitized review projection for unresolved academic evidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.persistence.models import Assignment, AssignmentEvidence, Claim


class EvidenceReviewService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.sessions() as session:
            claims = session.scalars(
                select(Claim)
                .options(
                    selectinload(Claim.source_record),
                    selectinload(Claim.assignment_links)
                    .selectinload(AssignmentEvidence.assignment)
                        .selectinload(Assignment.course),
                )
                .where(
                    or_(
                        Claim.validation_status != "validated",
                        ~Claim.assignment_links.any(),
                        Claim.assignment_links.any(
                            AssignmentEvidence.disposition != "admitted"
                        ),
                    )
                )
                .order_by(Claim.created_at.desc(), Claim.id.desc())
                .limit(max(1, min(limit, 250)))
            ).all()
            values = []
            for claim in claims:
                links = sorted(
                    claim.assignment_links,
                    key=lambda item: (item.assignment_match_score, item.id),
                    reverse=True,
                )
                pending = claim.validation_status != "validated" or not links or any(
                    item.disposition != "admitted" for item in links
                )
                if not pending:
                    continue
                link = links[0] if links else None
                assignment = link.assignment if link else None
                course = assignment.course if assignment else None
                due_at = claim.normalized_value.get("due_at")
                precision = claim.normalized_value.get(
                    "precision", link.precision if link else "unknown"
                )
                values.append(
                    {
                        "id": f"claim:{claim.id}",
                        "review_type": "academic_evidence",
                        "status": (
                            "rejected"
                            if claim.validation_status != "validated"
                            else link.disposition if link else "unmatched"
                        ),
                        "source_type": claim.source_record.source_type,
                        "course_name": course.name if course else None,
                        "assignment_id": assignment.id if assignment else None,
                        "assignment_title": assignment.canonical_title if assignment else None,
                        "claim_type": claim.claim_type,
                        "assignment_hint": claim.assignment_hint,
                        "candidate_due_at": due_at if isinstance(due_at, str) else None,
                        "precision": precision if isinstance(precision, str) else "unknown",
                        "confidence": _confidence(claim.extraction_confidence),
                        "reason": (
                            link.explanation
                            if link else "Claim needs assignment matching or validation review."
                        ),
                    }
                )
            return values


def _confidence(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.65:
        return "medium"
    return "low"
