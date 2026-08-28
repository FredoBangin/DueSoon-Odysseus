"""Owner-controlled notes, memory, and academic document catalog."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import (
    AcademicMemory,
    AcademicNote,
    Assignment,
    Course,
    SourceRecord,
)


MEMORY_TYPES = {"alias", "preference", "matching_feedback", "source_reliability"}
SCOPE_TYPES = {"assignment", "course", "sender", "global"}
DOCUMENT_TYPES = {"file", "page", "module", "module_item"}


class RetainedToolsService:
    """Safe academic primitives; no inherited tool execution or automatic truth changes."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def notes(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._sessions() as session:
            query = select(AcademicNote).order_by(
                AcademicNote.updated_at.desc(), AcademicNote.id.desc()
            )
            if not include_archived:
                query = query.where(AcademicNote.archived.is_(False))
            return [self._note_value(session, item) for item in session.scalars(query)]

    def create_note(
        self,
        *,
        title: str,
        body: str,
        assignment_id: int | None = None,
        course_id: int | None = None,
    ) -> dict[str, Any]:
        title = self._required(title, "note title")
        body = self._required(body, "note body")
        with self._sessions() as session:
            self._validate_refs(session, assignment_id, course_id)
            note = AcademicNote(
                public_id=str(uuid4()),
                title=title,
                body=body,
                assignment_id=assignment_id,
                course_id=course_id,
            )
            session.add(note)
            session.commit()
            return self._note_value(session, note)

    def update_note(
        self,
        public_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        with self._sessions() as session:
            note = session.scalar(
                select(AcademicNote).where(AcademicNote.public_id == public_id)
            )
            if note is None:
                raise LookupError("academic note not found")
            if title is not None:
                note.title = self._required(title, "note title")
            if body is not None:
                note.body = self._required(body, "note body")
            if archived is not None:
                note.archived = archived
            session.commit()
            return self._note_value(session, note)

    def memories(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        with self._sessions() as session:
            query = select(AcademicMemory).order_by(
                AcademicMemory.updated_at.desc(), AcademicMemory.id.desc()
            )
            if not include_inactive:
                query = query.where(AcademicMemory.active.is_(True))
            return [self._memory_value(item) for item in session.scalars(query)]

    def create_memory(
        self,
        *,
        memory_type: str,
        scope_type: str,
        scope_ref: str | None,
        label: str,
        value: str,
    ) -> dict[str, Any]:
        if memory_type not in MEMORY_TYPES:
            raise ValueError("invalid academic memory type")
        if scope_type not in SCOPE_TYPES:
            raise ValueError("invalid academic memory scope")
        label = self._required(label, "memory label")
        value = self._required(value, "memory value")
        with self._sessions() as session:
            item = AcademicMemory(
                public_id=str(uuid4()),
                memory_type=memory_type,
                scope_type=scope_type,
                scope_ref=scope_ref.strip() if scope_ref else None,
                label=label,
                value=value,
            )
            session.add(item)
            session.commit()
            return self._memory_value(item)

    def update_memory(
        self,
        public_id: str,
        *,
        label: str | None = None,
        value: str | None = None,
        active: bool | None = None,
    ) -> dict[str, Any]:
        with self._sessions() as session:
            item = session.scalar(
                select(AcademicMemory).where(AcademicMemory.public_id == public_id)
            )
            if item is None:
                raise LookupError("academic memory not found")
            if label is not None:
                item.label = self._required(label, "memory label")
            if value is not None:
                item.value = self._required(value, "memory value")
            if active is not None:
                item.active = active
            session.commit()
            return self._memory_value(item)

    def documents(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return sanitized Canvas evidence metadata, never raw bodies or signed URLs."""
        with self._sessions() as session:
            records = session.scalars(
                select(SourceRecord)
                .where(SourceRecord.source_type.in_(DOCUMENT_TYPES))
                .order_by(SourceRecord.observed_at.desc(), SourceRecord.id.desc())
                .limit(limit)
            ).all()
            course_ids = {item.course_id for item in records if item.course_id is not None}
            courses = {
                item.id: item.name
                for item in session.scalars(select(Course).where(Course.id.in_(course_ids)))
            } if course_ids else {}
            return [self._document_value(item, courses.get(item.course_id)) for item in records]

    @staticmethod
    def _validate_refs(
        session: Session, assignment_id: int | None, course_id: int | None
    ) -> None:
        if assignment_id is not None and session.get(Assignment, assignment_id) is None:
            raise LookupError("assignment not found")
        if course_id is not None and session.get(Course, course_id) is None:
            raise LookupError("course not found")

    @staticmethod
    def _required(value: str, field: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError(f"{field} cannot be blank")
        return clean

    @staticmethod
    def _note_value(session: Session, note: AcademicNote) -> dict[str, Any]:
        assignment = session.get(Assignment, note.assignment_id) if note.assignment_id else None
        course = session.get(Course, note.course_id) if note.course_id else None
        return {
            "id": note.public_id,
            "title": note.title,
            "body": note.body,
            "assignment_id": note.assignment_id,
            "assignment_title": assignment.canonical_title if assignment else None,
            "course_id": note.course_id,
            "course_name": course.name if course else None,
            "archived": note.archived,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }

    @staticmethod
    def _memory_value(item: AcademicMemory) -> dict[str, Any]:
        return {
            "id": item.public_id,
            "memory_type": item.memory_type,
            "scope_type": item.scope_type,
            "scope_ref": item.scope_ref,
            "label": item.label,
            "value": item.value,
            "active": item.active,
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def _document_value(item: SourceRecord, course_name: str | None) -> dict[str, Any]:
        payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
        title = (
            payload.get("display_name")
            or payload.get("title")
            or payload.get("name")
            or payload.get("filename")
            or f"Canvas {item.source_type}"
        )
        return {
            "id": f"canvas:{item.source_type}:{item.external_id}:{item.version}",
            "source_type": item.source_type,
            "title": str(title)[:500],
            "course_name": course_name,
            "content_type": str(payload.get("content-type") or payload.get("content_type") or "")[:200],
            "size": payload.get("size") if isinstance(payload.get("size"), int) else None,
            "observed_at": item.observed_at.isoformat(),
            "source": "canvas",
            "read_only": True,
            "version": item.version,
        }
