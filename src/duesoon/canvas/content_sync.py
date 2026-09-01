"""Read-only synchronization of Canvas communications and course content."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.canvas.client import CanvasAPIError
from src.duesoon.documents.extract import (
    DocumentExtractionError,
    SUPPORTED_CONTENT_TYPES,
    extract_document,
)
from src.duesoon.persistence.models import Course, SourceRecord


class CanvasContentReader(Protocol):
    def list_conversations(self, *, scope: str = "inbox") -> list[dict[str, Any]]: ...
    def get_conversation(self, conversation_id: str) -> dict[str, Any]: ...
    def list_announcements(
        self, course_ids: list[str], *, start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_modules(self, course_id: str) -> list[dict[str, Any]]: ...
    def list_module_items(
        self, course_id: str, module_id: str
    ) -> list[dict[str, Any]]: ...
    def list_files(self, course_id: str) -> list[dict[str, Any]]: ...
    def download_file(self, url: str, *, max_bytes: int) -> bytes: ...
    def list_pages(self, course_id: str) -> list[dict[str, Any]]: ...
    def get_page(self, course_id: str, page_url: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ContentSyncSummary:
    records_seen: int = 0
    source_versions_created: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    skipped_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanvasContentSyncService:
    """Persist append-only source records without interpreting them as truth."""

    def __init__(
        self,
        client: CanvasContentReader,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        announcement_lookback_days: int = 120,
        file_max_bytes: int = 8_000_000,
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.clock = clock
        self.announcement_lookback_days = announcement_lookback_days
        self.file_max_bytes = file_max_bytes

    def sync(self) -> ContentSyncSummary:
        observed_at = self.clock()
        records: list[tuple[str, str, int | None, dict[str, Any]]] = []
        skipped: dict[str, str] = {}

        with self.sessions() as session:
            courses = session.scalars(select(Course).where(Course.active.is_(True))).all()
            course_by_canvas_id = {course.canvas_course_id: course for course in courses}

            conversations = self._optional("conversations", self.client.list_conversations, skipped)
            for conversation in conversations:
                conversation_id = str(conversation.get("id", ""))
                if not conversation_id:
                    continue
                try:
                    detail = self.client.get_conversation(conversation_id)
                except CanvasAPIError:
                    detail = conversation
                course_id = self._conversation_course_id(detail, course_by_canvas_id)
                records.append(("conversation", conversation_id, course_id, detail))

            canvas_course_ids = list(course_by_canvas_id)
            start = (observed_at - timedelta(days=self.announcement_lookback_days)).date()
            announcements = self._optional(
                "announcements",
                lambda: self.client.list_announcements(
                    canvas_course_ids, start_date=start.isoformat()
                ),
                skipped,
            )
            for item in announcements:
                external_id = str(item.get("id", ""))
                if external_id:
                    records.append((
                        "announcement", external_id,
                        self._context_course_id(item.get("context_code"), course_by_canvas_id),
                        item,
                    ))

            for canvas_course_id, course in course_by_canvas_id.items():
                self._collect_course_content(
                    session, canvas_course_id, course.id, records, skipped
                )

            created = 0
            by_type: dict[str, int] = {}
            for source_type, external_id, course_id, payload in records:
                by_type[source_type] = by_type.get(source_type, 0) + 1
                created += int(self._store(
                    session,
                    source_type=source_type,
                    external_id=external_id,
                    course_id=course_id,
                    raw_payload=payload,
                    observed_at=observed_at,
                ))
            session.commit()

        return ContentSyncSummary(
            records_seen=len(records),
            source_versions_created=created,
            by_type=by_type,
            skipped_sources=skipped,
        )

    def _collect_course_content(
        self,
        session: Session,
        canvas_course_id: str,
        course_id: int,
        records: list[tuple[str, str, int | None, dict[str, Any]]],
        skipped: dict[str, str],
    ) -> None:
        prefix = f"course:{canvas_course_id}"
        module_page_urls: set[str] = set()
        modules = self._optional(
            f"{prefix}:modules",
            lambda: self.client.list_modules(canvas_course_id),
            skipped,
        )
        for module in modules:
            module_id = str(module.get("id", ""))
            if not module_id:
                continue
            records.append(("module", module_id, course_id, module))
            items = module.get("items")
            if not isinstance(items, list):
                items = self._optional(
                    f"{prefix}:module:{module_id}:items",
                    lambda mid=module_id: self.client.list_module_items(
                        canvas_course_id, mid
                    ),
                    skipped,
                )
            for item in items:
                item_id = str(item.get("id", ""))
                if item_id:
                    records.append(("module_item", item_id, course_id, item))
                page_url = item.get("page_url")
                if isinstance(page_url, str) and page_url:
                    module_page_urls.add(page_url)

        for item in self._optional(
            f"{prefix}:files", lambda: self.client.list_files(canvas_course_id), skipped
        ):
            external_id = str(item.get("id", ""))
            if external_id:
                records.append((
                    "file",
                    external_id,
                    course_id,
                    self._course_file_payload(
                        session, prefix, external_id, item, skipped
                    ),
                ))

        pages = self._optional(
            f"{prefix}:pages", lambda: self.client.list_pages(canvas_course_id), skipped
        )
        pages_by_url: dict[str, dict[str, Any]] = {}
        for page in pages:
            page_url = str(page.get("url", ""))
            if page_url:
                pages_by_url.setdefault(page_url, page)
        for page_url in sorted(module_page_urls):
            pages_by_url.setdefault(page_url, {"url": page_url})

        for page_url, page in pages_by_url.items():
            try:
                detail = self.client.get_page(canvas_course_id, page_url)
            except CanvasAPIError:
                detail = page
            records.append(("page", f"{canvas_course_id}:{page_url}", course_id, detail))

    def _course_file_payload(
        self,
        session: Session,
        prefix: str,
        external_id: str,
        item: dict[str, Any],
        skipped: dict[str, str],
    ) -> dict[str, Any]:
        payload = _sanitized_file_metadata(item)
        revision = _file_revision(item)
        payload["file_revision"] = revision
        prior = session.scalar(
            select(SourceRecord)
            .where(
                SourceRecord.source_system == "canvas",
                SourceRecord.source_type == "file",
                SourceRecord.external_id == external_id,
            )
            .order_by(SourceRecord.version.desc())
            .limit(1)
        )
        if prior is not None and isinstance(prior.raw_payload, dict):
            extraction = prior.raw_payload.get("extraction")
            if (
                prior.raw_payload.get("file_revision") == revision
                and isinstance(extraction, dict)
                and extraction.get("status") in {"extracted", "unsupported", "too_large"}
            ):
                return dict(prior.raw_payload)

        content_type = str(
            item.get("content-type") or item.get("content_type") or ""
        ).split(";", 1)[0].strip().casefold()
        filename = str(item.get("display_name") or item.get("filename") or "")[:255]
        size = item.get("size")
        if content_type not in SUPPORTED_CONTENT_TYPES:
            payload["extraction"] = {
                "status": "unsupported", "content_type": content_type
            }
            return payload
        if isinstance(size, int) and size > self.file_max_bytes:
            payload["extraction"] = {
                "status": "too_large", "content_type": content_type
            }
            return payload
        url = item.get("url")
        if not isinstance(url, str) or not url:
            payload["extraction"] = {"status": "download_unavailable"}
            skipped[f"{prefix}:file:{external_id}:content"] = "missing_url"
            return payload

        try:
            data = self.client.download_file(url, max_bytes=self.file_max_bytes)
            extracted = extract_document(
                data,
                filename=filename,
                content_type=content_type,
                max_bytes=self.file_max_bytes,
            )
        except CanvasAPIError as exc:
            payload["extraction"] = {"status": "download_unavailable"}
            skipped[f"{prefix}:file:{external_id}:content"] = (
                f"http_{exc.status_code}" if exc.status_code else "unavailable"
            )
            return payload
        except DocumentExtractionError:
            payload["extraction"] = {
                "status": "invalid", "content_type": content_type
            }
            skipped[f"{prefix}:file:{external_id}:content"] = "invalid_document"
            return payload

        payload["extracted_text"] = extracted.text
        payload["extraction"] = {
            "status": "extracted",
            "format": extracted.format,
            "locator_scheme": extracted.locator_scheme,
            "truncated": extracted.truncated,
        }
        return payload

    @staticmethod
    def _optional(
        name: str,
        operation: Callable[[], list[dict[str, Any]]],
        skipped: dict[str, str],
    ) -> list[dict[str, Any]]:
        try:
            return operation()
        except CanvasAPIError as exc:
            skipped[name] = f"http_{exc.status_code}" if exc.status_code else "unavailable"
            return []

    @staticmethod
    def _context_course_id(
        context_code: Any, course_by_canvas_id: dict[str, Course]
    ) -> int | None:
        if not isinstance(context_code, str) or not context_code.startswith("course_"):
            return None
        course = course_by_canvas_id.get(context_code.removeprefix("course_"))
        return course.id if course else None

    @classmethod
    def _conversation_course_id(
        cls, payload: dict[str, Any], course_by_canvas_id: dict[str, Course]
    ) -> int | None:
        candidates: set[str] = set()

        def add_context(value: Any) -> None:
            if isinstance(value, str) and value.startswith("course_"):
                candidates.add(value.removeprefix("course_"))

        add_context(payload.get("context_code"))
        add_context(payload.get("course_context"))
        direct_course = payload.get("course_id")
        if isinstance(direct_course, (str, int)):
            candidates.add(str(direct_course))
        course_ids = payload.get("course_ids")
        if isinstance(course_ids, (list, tuple, set)):
            candidates.update(str(value) for value in course_ids if isinstance(value, (str, int)))

        contexts = payload.get("audience_contexts")
        if isinstance(contexts, dict):
            courses = contexts.get("courses")
            if isinstance(courses, dict):
                candidates.update(str(value) for value in courses if isinstance(value, (str, int)))

        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict):
                    add_context(message.get("context_code"))

        known = {value for value in candidates if value in course_by_canvas_id}
        if len(known) != 1:
            return None
        return course_by_canvas_id[next(iter(known))].id

    @staticmethod
    def _store(
        session: Session,
        *,
        source_type: str,
        external_id: str,
        course_id: int | None,
        raw_payload: dict[str, Any],
        observed_at: datetime,
    ) -> bool:
        canonical = json.dumps(
            raw_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        existing = session.scalar(select(SourceRecord.id).where(
            SourceRecord.source_system == "canvas",
            SourceRecord.source_type == source_type,
            SourceRecord.external_id == external_id,
            SourceRecord.content_hash == content_hash,
        ))
        if existing is not None:
            return False
        version = session.scalar(
            select(func.count()).select_from(SourceRecord).where(
                SourceRecord.source_system == "canvas",
                SourceRecord.source_type == source_type,
                SourceRecord.external_id == external_id,
            )
        )
        record = SourceRecord(
            source_system="canvas",
            source_type=source_type,
            external_id=external_id,
            course_id=course_id,
            source_published_at=_source_timestamp(raw_payload),
            observed_at=observed_at,
            content_hash=content_hash,
            version=int(version or 0) + 1,
            raw_payload=raw_payload,
            parser_version="canvas-content-v1",
        )
        session.add(record)
        session.flush()
        return True


def _source_timestamp(payload: dict[str, Any]) -> datetime | None:
    for key in ("last_message_at", "posted_at", "updated_at", "created_at"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
            except ValueError:
                continue
    return None


def _sanitized_file_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop signed or preview URLs before academic metadata is persisted."""

    blocked = {"url", "preview_url", "thumbnail_url"}
    return {key: value for key, value in payload.items() if key not in blocked}


def _file_revision(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            key: payload.get(key)
            for key in (
                "id", "uuid", "filename", "display_name", "content-type",
                "content_type", "size", "updated_at", "modified_at",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
