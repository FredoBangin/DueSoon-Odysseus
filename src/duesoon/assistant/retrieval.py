"""Bounded, read-only retrieval for assistant questions."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import AcademicMemory, AcademicNote, Course, SourceRecord


SOURCE_TYPES = frozenset(
    {"assignment", "conversation", "announcement", "page", "module", "module_item", "message"}
)
STOP_WORDS = frozenset(
    {
        "a", "about", "an", "and", "any", "are", "did", "do", "for", "from",
        "has", "have", "i", "in", "is", "it", "me", "my", "of", "on", "or",
        "the", "to", "was", "what", "when", "where", "which", "who", "why",
    }
)
ACADEMIC_WORDS = frozenset(
    {
        "assignment", "canvas", "class", "course", "deadline", "due", "exam",
        "grade", "homework", "instructor", "lab", "professor", "quiz", "school",
        "submission", "syllabus",
    }
)


@dataclass(frozen=True)
class RetrievalContext:
    facts: tuple[dict[str, Any], ...]
    evidence_catalog: dict[str, dict[str, str]]
    sources_consulted: tuple[str, ...]
    assumptions: tuple[str, ...]
    missing_connections: tuple[str, ...]


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _plain(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = _Text()
    try:
        parser.feed(value)
        value = " ".join(parser.parts)
    except Exception:
        pass
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in STOP_WORDS
    }


def _source_text(source: SourceRecord) -> str:
    payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
    values: list[str] = []
    for key in ("title", "subject", "name", "display_name", "description", "message", "body", "content", "snippet"):
        value = _plain(payload.get(key))
        if value:
            values.append(value)
    messages = payload.get("messages")
    if isinstance(messages, list):
        for item in messages[:20]:
            if isinstance(item, dict):
                value = _plain(item.get("body"))
                if value:
                    values.append(value)
    return " ".join(values)[:4000]


def _relevant(question_tokens: set[str], text: str) -> bool:
    if not question_tokens or not text:
        return False
    candidates = _tokens(text)
    overlap = question_tokens & candidates
    return len(overlap) >= 2 or bool(overlap & ACADEMIC_WORDS)


class AssistantRetrievalService:
    """Retrieve minimal local facts; never calls applications or writes data."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        connections: dict[str, bool] | None = None,
    ) -> None:
        self.sessions = sessions
        self.connections = connections or {}

    def retrieve(self, question: str, snapshot: dict[str, Any]) -> RetrievalContext:
        tokens = _tokens(question)
        lower = question.casefold()
        missing: list[str] = []
        if any(word in lower for word in ("email", "gmail", "inbox")) and not self.connections.get("gmail"):
            missing.append("gmail_read_only")
        if any(word in lower for word in ("calendar", "schedule", "availability", "busy", "free time")) and not self.connections.get("google_calendar"):
            missing.append("google_calendar_read_only")

        facts: list[dict[str, Any]] = []
        catalog: dict[str, dict[str, str]] = {}
        consulted: list[str] = []
        assumptions: list[str] = []

        self._assignment_facts(tokens, snapshot, facts, catalog, consulted)
        with self.sessions() as session:
            self._source_facts(session, tokens, facts, catalog, consulted)
            self._note_facts(session, tokens, facts, catalog, consulted)
            self._memory_facts(session, tokens, facts, catalog, consulted)

        academic_question = bool(tokens & ACADEMIC_WORDS)
        if academic_question and not facts:
            assumptions.append("No matching connected academic evidence was found.")
        freshness = snapshot.get("freshness") if isinstance(snapshot.get("freshness"), dict) else {}
        if academic_question and freshness.get("canvas_status") == "stale":
            assumptions.append("Canvas data is stale; recent changes may be missing.")
        return RetrievalContext(
            facts=tuple(facts[:20]),
            evidence_catalog=dict(list(catalog.items())[:20]),
            sources_consulted=tuple(dict.fromkeys(consulted)),
            assumptions=tuple(assumptions),
            missing_connections=tuple(missing),
        )

    @staticmethod
    def _assignment_facts(tokens, snapshot, facts, catalog, consulted) -> None:
        for group in ("urgent", "upcoming", "overdue", "missing", "completed_recently"):
            for item in snapshot.get(group, []):
                text = f"{item.get('title', '')} {item.get('course_name', '')}"
                if not _relevant(tokens, text) and not tokens & ACADEMIC_WORDS:
                    continue
                evidence_id = f"assignment:{item['id']}"
                if evidence_id in catalog:
                    continue
                facts.append(
                    {
                        "evidence_id": evidence_id,
                        "source": "canvas_assignment",
                        "title": item.get("title"),
                        "course_name": item.get("course_name"),
                        "effective_due_at": item.get("effective_due_at"),
                        "submission_status": item.get("submission_status"),
                        "deadline_status": item.get("deadline_status"),
                        "deadline_confidence": item.get("deadline_confidence"),
                        "urgency": item.get("urgency"),
                    }
                )
                catalog[evidence_id] = {
                    "label": str(item.get("title") or "Canvas assignment"),
                    "href": str(item.get("external_url") or f"/app/calendar?assignment={item['id']}"),
                }
                consulted.append("canvas_assignment")
                if len(facts) >= 20:
                    return

    @staticmethod
    def _source_facts(session, tokens, facts, catalog, consulted) -> None:
        sources = session.scalars(
            select(SourceRecord)
            .where(SourceRecord.source_type.in_(SOURCE_TYPES))
            .order_by(SourceRecord.observed_at.desc(), SourceRecord.id.desc())
            .limit(100)
        ).all()
        course_ids = {item.course_id for item in sources if item.course_id is not None}
        courses = {
            item.id: item.name
            for item in session.scalars(select(Course).where(Course.id.in_(course_ids)))
        } if course_ids else {}
        for source in sources:
            text = _source_text(source)
            if not _relevant(tokens, text):
                continue
            evidence_id = (
                f"source:{source.source_system}:{source.source_type}:"
                f"{source.external_id}:{source.version}"
            )
            source_name = f"{source.source_system}_{source.source_type}"
            facts.append(
                {
                    "evidence_id": evidence_id,
                    "source": source_name,
                    "course_name": courses.get(source.course_id),
                    "published_at": (
                        source.source_published_at.isoformat()
                        if source.source_published_at else None
                    ),
                    "excerpt": text[:600],
                }
            )
            catalog[evidence_id] = {
                "label": f"{source.source_system.title()} {source.source_type.replace('_', ' ')}",
                "href": f"/app/review?evidence={source.id}",
            }
            consulted.append(source_name)
            if len(facts) >= 20:
                return

    @staticmethod
    def _note_facts(session, tokens, facts, catalog, consulted) -> None:
        notes = session.scalars(
            select(AcademicNote)
            .where(AcademicNote.archived.is_(False))
            .order_by(AcademicNote.updated_at.desc(), AcademicNote.id.desc())
            .limit(30)
        ).all()
        for note in notes:
            text = f"{note.title} {note.body}"
            if not _relevant(tokens, text):
                continue
            evidence_id = f"note:{note.public_id}"
            facts.append({"evidence_id": evidence_id, "source": "owner_note", "excerpt": text[:600]})
            catalog[evidence_id] = {"label": note.title, "href": "/app/notes"}
            consulted.append("owner_note")

    @staticmethod
    def _memory_facts(session, tokens, facts, catalog, consulted) -> None:
        memories = session.scalars(
            select(AcademicMemory)
            .where(AcademicMemory.active.is_(True))
            .order_by(AcademicMemory.updated_at.desc(), AcademicMemory.id.desc())
            .limit(30)
        ).all()
        for memory in memories:
            text = f"{memory.label} {memory.value}"
            if not _relevant(tokens, text):
                continue
            evidence_id = f"memory:{memory.public_id}"
            facts.append({"evidence_id": evidence_id, "source": "approved_memory", "excerpt": text[:600]})
            catalog[evidence_id] = {"label": memory.label, "href": "/app/memory"}
            consulted.append("approved_memory")
