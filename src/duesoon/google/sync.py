"""Automatic read-only Google Workspace synchronization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import SchedulerState

from .availability import GoogleCalendarEvidenceService
from .evidence import GoogleEvidenceService


STATE_KEY = "google_workspace_sync"
logger = logging.getLogger(__name__)


class GoogleReader(Protocol):
    config: Any

    def list_gmail_messages(self, *, query: str, limit: int) -> list[dict[str, Any]]: ...

    def list_calendar_events(
        self, *, start: datetime, end: datetime, limit: int = 250
    ) -> list[dict[str, Any]]: ...


class EvidencePipeline(Protocol):
    def process_pending(self, *, limit: int = 5) -> Any: ...


class GoogleWorkspaceSyncService:
    """Refresh connected Google evidence without making Gmail or Calendar writes."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        client: GoogleReader,
        gmail: GoogleEvidenceService,
        calendar: GoogleCalendarEvidenceService,
        pipeline: EvidencePipeline,
        *,
        should_extract: Callable[[], bool] = lambda: False,
        interval_seconds: int = 900,
        extraction_retry_seconds: int = 3600,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.client = client
        self.gmail = gmail
        self.calendar = calendar
        self.pipeline = pipeline
        self.should_extract = should_extract
        self.interval_seconds = max(300, interval_seconds)
        self.extraction_retry_seconds = max(900, extraction_retry_seconds)
        self.clock = clock
        self._extraction_retry_at: datetime | None = None

    def run_once(self) -> dict[str, Any]:
        now = _utc(self.clock())
        with self.sessions() as session:
            state = session.get(SchedulerState, STATE_KEY)
            if (
                state is not None
                and state.last_successful_at is not None
                and now - _utc(state.last_successful_at)
                < timedelta(seconds=self.interval_seconds)
            ):
                return {"status": "skipped_interval"}

        result: dict[str, Any] = {"status": "synced"}
        if bool(getattr(self.client.config, "gmail_enabled", False)):
            messages = self.client.list_gmail_messages(
                query="label:inbox newer_than:90d",
                limit=50,
            )
            result["gmail"] = self.gmail.store_messages(messages, observed_at=now)

        if bool(getattr(self.client.config, "calendar_enabled", False)):
            start, end = now - timedelta(days=1), now + timedelta(days=60)
            events = self.client.list_calendar_events(start=start, end=end)
            result["calendar"] = self.calendar.store_events(
                events,
                observed_at=now,
                window_start=start,
                window_end=end,
            )

        if (
            self.should_extract()
            and self._extraction_retry_at is not None
            and now < self._extraction_retry_at
        ):
            result["extraction"] = {"status": "skipped_backoff"}
        elif self.should_extract():
            try:
                summary = self.pipeline.process_pending(limit=10)
                result["extraction"] = summary.to_dict()
                self._extraction_retry_at = None
            except Exception as exc:
                # Source capture remains successful. Ingested records stay queued for
                # the next bounded extraction cycle.
                self._extraction_retry_at = now + timedelta(
                    seconds=self.extraction_retry_seconds
                )
                logger.warning(
                    "automatic academic evidence extraction failed; backoff active (%s)",
                    type(exc).__name__,
                )
                result["extraction"] = {"status": "failed_backoff"}

        with self.sessions() as session:
            state = session.get(SchedulerState, STATE_KEY)
            if state is None:
                state = SchedulerState(key=STATE_KEY)
                session.add(state)
            state.last_successful_at = now
            session.commit()
        return result


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
