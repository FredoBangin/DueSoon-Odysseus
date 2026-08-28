from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from src.duesoon.canvas.content_sync import CanvasContentSyncService
from src.duesoon.config.settings import DueSoonSettings
from src.duesoon.persistence.database import (
    create_engine_from_settings,
    create_schema,
    session_factory,
)
from src.duesoon.persistence.models import Course, SourceRecord


class AcademicContentStub:
    def list_conversations(self, *, scope: str = "inbox"):
        assert scope == "inbox"
        return [{"id": 1, "subject": "Lab moved"}]

    def get_conversation(self, conversation_id: str):
        return {
            "id": int(conversation_id),
            "subject": "Lab moved",
            "audience_contexts": {"courses": {"42": []}},
            "messages": [{"id": 2, "body": "Due Friday"}],
        }

    def list_announcements(self, course_ids, *, start_date=None, end_date=None):
        assert course_ids == ["42"] and start_date
        return [{"id": 3, "context_code": "course_42", "message": "Read syllabus"}]

    def list_modules(self, course_id: str):
        return [{"id": 4, "name": "Week 1"}]

    def list_module_items(self, course_id: str, module_id: str):
        return [{"id": 5, "title": "Lab", "type": "Assignment"}]

    def list_files(self, course_id: str):
        return [{"id": 6, "display_name": "syllabus.pdf"}]

    def list_pages(self, course_id: str):
        return [{"url": "week-1"}]

    def get_page(self, course_id: str, page_url: str):
        return {"url": page_url, "body": "Office hours Thursday"}


def test_content_sync_is_append_only_and_idempotent(tmp_path: Path) -> None:
    settings = DueSoonSettings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'content.db').as_posix()}",
    )
    engine = create_engine_from_settings(settings)
    create_schema(engine)
    sessions = session_factory(engine)
    with sessions() as session:
        session.add(Course(canvas_course_id="42", name="Biology", active=True))
        session.commit()

    service = CanvasContentSyncService(
        AcademicContentStub(),
        sessions,
        clock=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )
    first = service.sync()
    second = service.sync()

    assert first.records_seen == 6
    assert first.source_versions_created == 6
    assert second.source_versions_created == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 6
        conversation = session.scalar(
            select(SourceRecord).where(SourceRecord.source_type == "conversation")
        )
        assert conversation is not None
        assert conversation.course_id is not None
        assert conversation.raw_payload["messages"][0]["body"] == "Due Friday"
