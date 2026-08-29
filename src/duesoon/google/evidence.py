"""Persist read-only Gmail messages as versioned academic evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import SourceRecord


class GoogleEvidenceService:
    """Store Gmail evidence without promoting it to canonical academic truth."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def store_messages(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, int]:
        observed_at = observed_at or datetime.now(UTC)
        stored = unchanged = 0
        with self._sessions() as session:
            for message in messages:
                external_id = str(message.get("id") or "").strip()
                if not external_id:
                    continue
                payload = self._payload(message)
                canonical = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                exists = session.scalar(
                    select(SourceRecord.id).where(
                        SourceRecord.source_system == "gmail",
                        SourceRecord.source_type == "message",
                        SourceRecord.external_id == external_id,
                        SourceRecord.content_hash == content_hash,
                    )
                )
                if exists is not None:
                    unchanged += 1
                    continue
                version = session.scalar(
                    select(func.count()).select_from(SourceRecord).where(
                        SourceRecord.source_system == "gmail",
                        SourceRecord.source_type == "message",
                        SourceRecord.external_id == external_id,
                    )
                )
                session.add(
                    SourceRecord(
                        source_system="gmail",
                        source_type="message",
                        external_id=external_id,
                        course_id=None,
                        source_published_at=self._published_at(payload.get("date")),
                        observed_at=observed_at,
                        content_hash=content_hash,
                        version=int(version or 0) + 1,
                        raw_payload=payload,
                        parser_version="gmail-readonly-v1",
                    )
                )
                stored += 1
            session.commit()
        return {"stored": stored, "unchanged": unchanged}

    @staticmethod
    def _payload(message: dict[str, Any]) -> dict[str, Any]:
        return {
            "thread_id": str(message.get("thread_id") or "")[:255],
            "subject": str(message.get("subject") or "(no subject)")[:500],
            "from": str(message.get("from") or "")[:500],
            "date": str(message.get("date") or "")[:200],
            "snippet": str(message.get("snippet") or "")[:1000],
            "body": str(message.get("body") or "")[:20000],
            "attachments": list(message.get("attachments") or [])[:25],
        }

    @staticmethod
    def _published_at(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
