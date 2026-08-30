"""Owner-confirmed professor sender identity and course scoping."""

from __future__ import annotations

import hashlib
import re
from email.utils import parseaddr
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import (
    Claim,
    Course,
    CourseInstructorIdentity,
    SourceRecord,
)


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    email = parseaddr(value)[1].strip().casefold()
    if not EMAIL_PATTERN.fullmatch(email) or len(email) > 320:
        raise ValueError("valid professor email is required")
    return email


def professor_email_hash(value: str) -> str:
    return hashlib.sha256(f"duesoon-professor:{normalize_email(value)}".encode()).hexdigest()


def masked_email(value: str) -> str:
    local, domain = normalize_email(value).split("@", 1)
    return f"{local[0]}***@{domain}"


def verified_sender_course(session: Session, sender: str | None) -> int | None:
    if not sender:
        return None
    try:
        digest = professor_email_hash(sender)
    except ValueError:
        return None
    course_ids = set(
        session.scalars(
            select(CourseInstructorIdentity.course_id).where(
                CourseInstructorIdentity.email_hash == digest,
                CourseInstructorIdentity.active.is_(True),
                CourseInstructorIdentity.owner_confirmed.is_(True),
            )
        ).all()
    )
    return next(iter(course_ids)) if len(course_ids) == 1 else None


class ProfessorIdentityService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def verify(
        self,
        *,
        course_id: int,
        email: str,
        source_kind: str = "owner",
        source_claim_id: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_email(email)
        digest = professor_email_hash(normalized)
        label = masked_email(normalized)
        with self.sessions() as session:
            course = session.get(Course, course_id)
            if course is None:
                raise LookupError("course not found")
            row = session.scalar(
                select(CourseInstructorIdentity).where(
                    CourseInstructorIdentity.course_id == course_id,
                    CourseInstructorIdentity.email_hash == digest,
                )
            )
            if row is None:
                row = CourseInstructorIdentity(
                    course_id=course_id,
                    email_hash=digest,
                    sender_label=label,
                    source_kind=source_kind[:50],
                    source_claim_id=source_claim_id,
                    owner_confirmed=True,
                    active=True,
                )
                session.add(row)
            else:
                row.sender_label = label
                row.source_kind = source_kind[:50]
                row.source_claim_id = source_claim_id or row.source_claim_id
                row.owner_confirmed = True
                row.active = True
            self._requeue_sender(session, digest)
            session.commit()
            session.refresh(row)
            return self._view(row, course.name)

    def confirm_claim(self, claim_id: int) -> dict[str, Any]:
        with self.sessions() as session:
            claim = session.get(Claim, claim_id)
            if claim is None:
                raise LookupError("claim not found")
            source = claim.source_record
            if (
                claim.claim_type != "professor_identity"
                or claim.validation_status != "validated"
                or source.course_id is None
            ):
                raise ValueError("claim cannot verify a course professor")
            email = claim.normalized_value.get("email")
            if not isinstance(email, str):
                raise ValueError("professor identity claim has no valid email")
            course_id = source.course_id
        return self.verify(
            course_id=course_id,
            email=email,
            source_kind="syllabus_claim",
            source_claim_id=claim_id,
        )

    def list_verified(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.execute(
                select(CourseInstructorIdentity, Course.name)
                .join(Course, Course.id == CourseInstructorIdentity.course_id)
                .where(CourseInstructorIdentity.active.is_(True))
                .order_by(Course.name, CourseInstructorIdentity.id)
            ).all()
            return [self._view(identity, course_name) for identity, course_name in rows]

    def course_options(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            courses = session.scalars(
                select(Course)
                .where(Course.active.is_(True))
                .order_by(Course.name, Course.id)
            ).all()
            return [{"id": course.id, "name": course.name} for course in courses]

    @staticmethod
    def _requeue_sender(session: Session, digest: str) -> None:
        sources = session.scalars(
            select(SourceRecord).where(
                SourceRecord.source_system == "gmail",
                SourceRecord.source_type == "message",
            )
        ).all()
        for source in sources:
            payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
            sender = payload.get("from")
            if isinstance(sender, str):
                try:
                    matches = professor_email_hash(sender) == digest
                except ValueError:
                    matches = False
                if matches:
                    source.ingestion_status = "ingested"

    @staticmethod
    def _view(identity: CourseInstructorIdentity, course_name: str) -> dict[str, Any]:
        return {
            "id": identity.id,
            "course_id": identity.course_id,
            "course_name": course_name,
            "sender": identity.sender_label,
            "source_kind": identity.source_kind,
            "owner_confirmed": identity.owner_confirmed,
            "active": identity.active,
        }
