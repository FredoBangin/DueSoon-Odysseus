"""Owner-reviewed, reversible assistant learning proposals."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import (
    AssistantExchange,
    AssistantFeedback,
    LearningAuditEvent,
    LearningProposal,
    LearningReversal,
)


ALLOWED_SCOPES = {"assignment", "course", "sender", "global"}
ALLOWED_ACTIONS = {"approve", "reject", "undo"}


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _behavior_type(correction: str) -> str:
    text = _normalized(correction)
    explicit_format = (
        ("answer" in text and any(word in text for word in ("shorter", "concise", "format", "bullet")))
        or "use bullet" in text
        or "be concise" in text
    )
    return "answer_format_preference" if explicit_format else "assistant_explanation"


class LearningService:
    """Learning affects explanations only; canonical academic state stays untouched."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def submit_feedback(
        self,
        answer_id: str,
        *,
        verdict: str,
        what_was_wrong: str | None = None,
        scope_type: str = "global",
        scope_ref: str | None = None,
    ) -> dict[str, Any]:
        if verdict not in {"correct", "incorrect", "uncertain"}:
            raise ValueError("invalid feedback verdict")
        if scope_type not in ALLOWED_SCOPES:
            raise ValueError("invalid learning scope")
        with self._sessions() as session:
            exchange = session.scalar(
                select(AssistantExchange).where(AssistantExchange.public_id == answer_id)
            )
            if exchange is None:
                raise LookupError("assistant answer not found")
            feedback = session.scalar(
                select(AssistantFeedback).where(
                    AssistantFeedback.exchange_id == exchange.id
                )
            )
            if feedback is None:
                feedback = AssistantFeedback(
                    public_id=str(uuid4()),
                    exchange_id=exchange.id,
                    verdict=verdict,
                    correction_prompted=verdict != "correct" and not what_was_wrong,
                    what_was_wrong=what_was_wrong,
                )
                session.add(feedback)
                session.flush()
            else:
                feedback.verdict = verdict
                feedback.what_was_wrong = what_was_wrong
                feedback.correction_prompted = verdict != "correct" and not what_was_wrong

            proposal = None
            if verdict != "correct" and what_was_wrong:
                clean = what_was_wrong.strip()
                behavior_type = _behavior_type(clean)
                proposal = session.scalar(
                    select(LearningProposal).where(
                        LearningProposal.feedback_id == feedback.id
                    )
                )
                if proposal is None:
                    candidates = session.scalars(
                        select(LearningProposal).where(
                            LearningProposal.behavior_type == behavior_type,
                            LearningProposal.scope_type == scope_type,
                            LearningProposal.scope_ref == scope_ref,
                        )
                    ).all()
                    proposal = next(
                        (
                            item
                            for item in candidates
                            if _normalized(item.after_text) == _normalized(clean)
                        ),
                        None,
                    )
                    if proposal is not None:
                        reference = f"assistant:{answer_id}"
                        if reference not in proposal.source_refs:
                            before = self._serialize(proposal)
                            proposal.source_refs = [*proposal.source_refs, reference]
                            session.flush()
                            self._audit(session, proposal, "corroborate", before)
                    else:
                        automatic = behavior_type == "answer_format_preference"
                        proposal = LearningProposal(
                            public_id=str(uuid4()),
                            feedback_id=feedback.id,
                            behavior_type=behavior_type,
                            scope_type=scope_type,
                            scope_ref=scope_ref,
                            before_text=exchange.answer,
                            after_text=clean,
                            explanation=(
                                "Explicit owner formatting preference applied automatically."
                                if automatic
                                else "Owner correction proposed for future assistant explanations."
                            ),
                            source_refs=[f"assistant:{answer_id}"],
                            affected_future_behavior=(
                                "May change answer length and formatting only. Cannot alter facts, "
                                "deadlines, submissions, urgency, or reminders."
                                if automatic
                                else "May guide future explanations and matching suggestions only. "
                                "Cannot alter deadlines, submissions, urgency, or reminders."
                            ),
                            created_by=(
                                "automatic_low_risk" if automatic else "owner"
                            ),
                        )
                        session.add(proposal)
                        session.flush()
                        self._audit(session, proposal, "propose", None)
                        if automatic:
                            before = self._serialize(proposal)
                            proposal.status = "approved"
                            proposal.approved_at = datetime.now(UTC)
                            session.flush()
                            self._audit(
                                session,
                                proposal,
                                "auto_approve",
                                before,
                                actor="automatic_low_risk",
                            )
            session.commit()
            return {
                "feedback_id": feedback.public_id,
                "needs_correction": feedback.correction_prompted,
                "question": (
                    "What was wrong, and what should DueSoon understand next time?"
                    if feedback.correction_prompted else None
                ),
                "proposal": (
                    self._serialize_with_audit(session, proposal) if proposal else None
                ),
            }

    def list_proposals(self) -> list[dict[str, Any]]:
        with self._sessions() as session:
            values = session.scalars(
                select(LearningProposal).order_by(
                    LearningProposal.updated_at.desc(), LearningProposal.id.desc()
                )
            ).all()
            return [self._serialize_with_audit(session, value) for value in values]

    def act(
        self,
        public_id: str,
        *,
        action: str,
        edited_text: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS and action != "edit":
            raise ValueError("invalid review action")
        with self._sessions() as session:
            proposal = session.scalar(
                select(LearningProposal).where(LearningProposal.public_id == public_id)
            )
            if proposal is None:
                raise LookupError("learning proposal not found")
            before = self._serialize(proposal)
            now = datetime.now(UTC)
            if action == "approve":
                if proposal.status not in {"proposed", "rejected"}:
                    raise ValueError("proposal cannot be approved from its current state")
                proposal.status = "approved"
                proposal.approved_at = now
                proposal.rejected_at = None
            elif action == "reject":
                if proposal.status not in {"proposed", "approved"}:
                    raise ValueError("proposal cannot be rejected from its current state")
                proposal.status = "rejected"
                proposal.rejected_at = now
            elif action == "edit":
                if not edited_text or not edited_text.strip():
                    raise ValueError("edited text is required")
                proposal.after_text = edited_text.strip()
                proposal.status = "proposed"
                proposal.revision += 1
            else:
                if proposal.status not in {"approved", "rejected"}:
                    raise ValueError("proposal cannot be undone from its current state")
                proposal.status = "reverted"
                proposal.reverted_at = now
            session.flush()
            audit = self._audit(session, proposal, action, before)
            if action == "undo":
                session.add(LearningReversal(
                    proposal_id=proposal.id,
                    audit_event_id=audit.id,
                    reason=reason,
                ))
            session.commit()
            return self._serialize_with_audit(session, proposal)

    def context_for(
        self, _question: str, _snapshot: dict[str, Any]
    ) -> list[dict[str, str | None]]:
        with self._sessions() as session:
            approved = session.scalars(
                select(LearningProposal)
                .where(LearningProposal.status == "approved")
                .order_by(LearningProposal.updated_at.desc())
                .limit(10)
            ).all()
            return [
                {
                    "scope_type": item.scope_type,
                    "scope_ref": item.scope_ref,
                    "guidance": item.after_text,
                }
                for item in approved
            ]

    @staticmethod
    def _audit(
        session: Session,
        proposal: LearningProposal,
        action: str,
        before: dict[str, Any] | None,
        *,
        actor: str = "owner",
    ) -> LearningAuditEvent:
        event = LearningAuditEvent(
            proposal_id=proposal.id,
            action=action,
            before_state=before,
            after_state=LearningService._serialize(proposal),
            revision=proposal.revision,
            actor=actor,
        )
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def _serialize(proposal: LearningProposal | None) -> dict[str, Any] | None:
        if proposal is None:
            return None
        return {
            "id": proposal.public_id,
            "behavior_type": proposal.behavior_type,
            "scope_type": proposal.scope_type,
            "scope_ref": proposal.scope_ref,
            "before": proposal.before_text,
            "after": proposal.after_text,
            "explanation": proposal.explanation,
            "source_refs": proposal.source_refs,
            "affected_future_behavior": proposal.affected_future_behavior,
            "status": proposal.status,
            "revision": proposal.revision,
            "created_by": proposal.created_by,
            "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
            "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
        }

    @staticmethod
    def _serialize_with_audit(
        session: Session, proposal: LearningProposal
    ) -> dict[str, Any]:
        value = LearningService._serialize(proposal)
        assert value is not None
        events = session.scalars(
            select(LearningAuditEvent)
            .where(LearningAuditEvent.proposal_id == proposal.id)
            .order_by(LearningAuditEvent.id)
        ).all()
        value["audit"] = [
            {
                "action": item.action,
                "revision": item.revision,
                "actor": item.actor,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in events
        ]
        value["reversible"] = proposal.status in {"approved", "rejected"}
        return value
