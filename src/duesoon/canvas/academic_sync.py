"""Fault-isolated aggregate Canvas synchronization."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable


logger = logging.getLogger(__name__)


class CanvasAcademicSync:
    """Keep assignment/reminder sync authoritative while enriching evidence safely."""

    def __init__(
        self,
        core: Any,
        content: Any,
        *,
        evidence: Any | None = None,
        content_interval_seconds: int = 1800,
        evidence_retry_seconds: int = 3600,
        should_extract: Callable[[], bool] = lambda: True,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.core = core
        self.content = content
        self.evidence = evidence
        self.content_interval_seconds = content_interval_seconds
        self.evidence_retry_seconds = max(900, evidence_retry_seconds)
        self.should_extract = should_extract
        self.monotonic = monotonic
        self.last_content_summary: dict[str, Any] | None = None
        self.last_evidence_summary: dict[str, Any] | None = None
        self._last_content_sync: float | None = None
        self._evidence_retry_at: float | None = None

    def sync(self):
        summary = self.core.sync()
        now = self.monotonic()
        if self._last_content_sync is None or (
            now - self._last_content_sync >= self.content_interval_seconds
        ):
            self._last_content_sync = now
            try:
                self.last_content_summary = self.content.sync().to_dict()
            except Exception:
                # Optional evidence must never stop canonical Canvas reminders.
                self.last_content_summary = {"status": "failed"}
                logger.exception("Canvas content enrichment failed")
            if self.evidence is not None and not self.should_extract():
                self.last_evidence_summary = {"status": "disabled"}
            elif (
                self.evidence is not None
                and self._evidence_retry_at is not None
                and now < self._evidence_retry_at
            ):
                self.last_evidence_summary = {"status": "skipped_backoff"}
            elif self.evidence is not None:
                try:
                    self.last_evidence_summary = self.evidence.process_pending().to_dict()
                    self._evidence_retry_at = None
                except Exception as exc:
                    self._evidence_retry_at = now + self.evidence_retry_seconds
                    self.last_evidence_summary = {"status": "failed_backoff"}
                    logger.warning(
                        "Canvas evidence extraction failed; backoff active (%s)",
                        type(exc).__name__,
                    )
        return summary

    def refresh_submission(self, assignment_id: int) -> str:
        return self.core.refresh_submission(assignment_id)
