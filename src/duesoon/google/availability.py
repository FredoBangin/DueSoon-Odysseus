"""Privacy-minimized Google Calendar availability evidence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.duesoon.persistence.models import CalendarBusyBlock


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


class GoogleCalendarEvidenceService:
    """Store only busy intervals needed for planning, never event text."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def store_events(
        self,
        events: Iterable[dict[str, Any]],
        *,
        observed_at: datetime | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, int]:
        observed_at = _utc(observed_at or datetime.now(UTC))
        if (window_start is None) != (window_end is None):
            raise ValueError("calendar reconciliation requires both window bounds")
        if window_start is not None and window_end is not None:
            window_start, window_end = _utc(window_start), _utc(window_end)
            if window_end <= window_start:
                raise ValueError("calendar reconciliation window must be ordered")
        stored = updated = ignored = deactivated = 0
        seen_hashes: set[str] = set()
        with self.sessions() as session:
            for event in events:
                external_id = str(event.get("id") or "").strip()
                starts_at = _timestamp(event.get("starts_at"))
                ends_at = _timestamp(event.get("ends_at"))
                if (
                    not external_id
                    or str(event.get("status", "confirmed")).casefold() == "cancelled"
                    or starts_at is None
                    or ends_at is None
                    or ends_at <= starts_at
                ):
                    ignored += 1
                    continue
                external_hash = hashlib.sha256(
                    f"google_calendar:{external_id}".encode("utf-8")
                ).hexdigest()
                seen_hashes.add(external_hash)
                row = session.scalar(
                    select(CalendarBusyBlock).where(
                        CalendarBusyBlock.source_system == "google_calendar",
                        CalendarBusyBlock.external_id_hash == external_hash,
                    )
                )
                if row is None:
                    session.add(
                        CalendarBusyBlock(
                            source_system="google_calendar",
                            external_id_hash=external_hash,
                            starts_at=starts_at,
                            ends_at=ends_at,
                            all_day=bool(event.get("all_day")),
                            active=True,
                            observed_at=observed_at,
                        )
                    )
                    stored += 1
                elif (
                    _utc(row.starts_at) != starts_at
                    or _utc(row.ends_at) != ends_at
                    or row.all_day != bool(event.get("all_day"))
                    or not row.active
                ):
                    row.starts_at = starts_at
                    row.ends_at = ends_at
                    row.all_day = bool(event.get("all_day"))
                    row.active = True
                    row.observed_at = observed_at
                    updated += 1
            if window_start is not None and window_end is not None:
                existing = session.scalars(
                    select(CalendarBusyBlock).where(
                        CalendarBusyBlock.source_system == "google_calendar",
                        CalendarBusyBlock.active.is_(True),
                        CalendarBusyBlock.ends_at > window_start,
                        CalendarBusyBlock.starts_at < window_end,
                    )
                ).all()
                for row in existing:
                    if row.external_id_hash not in seen_hashes:
                        row.active = False
                        row.observed_at = observed_at
                        deactivated += 1
            session.commit()
        result = {
            "stored": stored,
            "updated": updated,
            "ignored": ignored,
        }
        if window_start is not None:
            result["deactivated"] = deactivated
        return result

    def summary(self, *, start: datetime, end: datetime) -> dict[str, Any]:
        start, end = _utc(start), _utc(end)
        if end <= start:
            raise ValueError("availability range must be ordered")
        with self.sessions() as session:
            rows = session.scalars(
                select(CalendarBusyBlock).where(
                    CalendarBusyBlock.active.is_(True),
                    CalendarBusyBlock.ends_at > start,
                    CalendarBusyBlock.starts_at < end,
                )
            ).all()
        intervals = [
            (max(start, _utc(row.starts_at)), min(end, _utc(row.ends_at)))
            for row in rows
        ]
        blocked = _merged_minutes(intervals)
        days_with_blocks = len(
            {
                (left + timedelta(days=offset)).date()
                for left, right in intervals
                for offset in range(max(1, ceil((right - left).total_seconds() / 86400)))
            }
        )
        total_days = max(1, ceil((end - start).total_seconds() / 86400))
        return {
            "blocked_minutes": blocked,
            "days_with_blocks": min(days_with_blocks, total_days),
            "days_without_blocks": max(0, total_days - days_with_blocks),
            "usable_capacity_minutes": None,
            "confidence": "low",
            "assumption": (
                "Calendar blocks are known, but flexible school capacity remains unknown."
            ),
        }


def _merged_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return round(sum((end - start).total_seconds() for start, end in merged) / 60)
