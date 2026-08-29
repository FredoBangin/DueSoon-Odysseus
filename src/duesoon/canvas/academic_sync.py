"""Fault-isolated aggregate Canvas synchronization."""

from __future__ import annotations

import logging
import time
from typing import Any


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
    ) -> None:
        self.core = core
        self.content = content
        self.evidence = evidence
        self.content_interval_seconds = content_interval_seconds
        self.last_content_summary: dict[str, Any] | None = None
        self.last_evidence_summary: dict[str, Any] | None = None
        self._last_content_sync: float | None = None

    def sync(self):
        summary = self.core.sync()
        now = time.monotonic()
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
            if self.evidence is not None:
                try:
                    self.last_evidence_summary = self.evidence.process_pending().to_dict()
                except Exception:
                    self.last_evidence_summary = {"status": "failed"}
                    logger.exception("Canvas evidence extraction failed")
        return summary

    def refresh_submission(self, assignment_id: int) -> str:
        return self.core.refresh_submission(assignment_id)
