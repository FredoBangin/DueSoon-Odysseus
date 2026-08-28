"""Stable human-readable urgency explanations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc(value: datetime) -> datetime:
    """Normalize naive and aware timestamps for deterministic arithmetic."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def compact_duration(value: timedelta) -> str:
    """Format an absolute duration without false decimal precision."""

    total_minutes = max(0, int(abs(value.total_seconds()) // 60))
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts[:2])


def due_reason(remaining: timedelta | None) -> str:
    if remaining is None:
        return "No precise operational deadline is available"
    if remaining.total_seconds() < 0:
        return f"Overdue by {compact_duration(remaining)} and incomplete"
    return f"Due in {compact_duration(remaining)}"


def timestamp_label(value: datetime) -> str:
    return utc(value).strftime("%Y-%m-%d %H:%M UTC")
