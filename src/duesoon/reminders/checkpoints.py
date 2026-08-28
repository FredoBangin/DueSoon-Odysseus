"""Checkpoint crossing rules for assignment reminders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


CHECKPOINT_MINUTES = (1440, 720, 360, 60, 15)


def crossed_checkpoint(
    due_at: datetime,
    previous_evaluated_at: datetime | None,
    now: datetime,
) -> int | None:
    """Return only the most recent checkpoint crossed in this evaluation."""

    deadline = _as_utc(due_at)
    current = _as_utc(now)
    if deadline <= current:
        return None

    if previous_evaluated_at is None:
        remaining = deadline - current
        if remaining > timedelta(minutes=CHECKPOINT_MINUTES[0]):
            return None
        for minutes in reversed(CHECKPOINT_MINUTES):
            if remaining <= timedelta(minutes=minutes):
                return minutes
        return None

    previous = _as_utc(previous_evaluated_at)
    crossed = [
        minutes
        for minutes in CHECKPOINT_MINUTES
        if previous < deadline - timedelta(minutes=minutes) <= current
    ]
    return min(crossed) if crossed else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
