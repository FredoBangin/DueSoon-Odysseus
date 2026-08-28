"""Deterministic, course-scoped assignment entity matching."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Iterable


HIGH_MATCH = 0.85
MEDIUM_MATCH = 0.65
AMBIGUITY_MARGIN = 0.08

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}


def normalize_assignment_title(value: str) -> str:
    """Normalize punctuation, Unicode, case, and small written numbers."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    words = re.findall(r"[a-z0-9]+", normalized)
    return " ".join(_NUMBER_WORDS.get(word, word) for word in words)


def _tokens(value: str) -> set[str]:
    return set(normalize_assignment_title(value).split())


def _numbers(value: str) -> set[str]:
    return {token for token in _tokens(value) if token.isdigit()}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class AssignmentReference:
    assignment_id: int
    course_id: int
    canonical_title: str
    aliases: tuple[str, ...] = ()
    canvas_assignment_id: str | None = None
    canonical_url: str | None = None
    assignment_type: str | None = None
    due_at: datetime | None = None


@dataclass(frozen=True)
class AssignmentHint:
    course_id: int | None
    assignment_hint: str | None = None
    canvas_assignment_id: str | None = None
    canonical_url: str | None = None
    assignment_type: str | None = None
    candidate_due_at: datetime | None = None


@dataclass(frozen=True)
class AssignmentMatch:
    assignment_id: int | None
    score: float
    confidence: str
    disposition: str
    reasons: tuple[str, ...]
    alternatives: tuple[tuple[int, float], ...] = ()


def _score_title(hint: str, reference: AssignmentReference) -> tuple[float, str]:
    normalized_hint = normalize_assignment_title(hint)
    names = (reference.canonical_title, *reference.aliases)
    normalized_names = tuple(normalize_assignment_title(name) for name in names)
    if normalized_hint == normalized_names[0]:
        return 0.85, "exact canonical title"
    if normalized_hint in normalized_names[1:]:
        return 0.82, "exact course-scoped alias"

    hint_tokens = _tokens(hint)
    best = 0.0
    for name in names:
        name_tokens = _tokens(name)
        union = hint_tokens | name_tokens
        jaccard = len(hint_tokens & name_tokens) / len(union) if union else 0.0
        sequence = SequenceMatcher(None, normalized_hint, normalize_assignment_title(name)).ratio()
        best = max(best, 0.70 * (0.70 * jaccard + 0.30 * sequence))
    return best, "normalized token and sequence similarity"


def _score(hint: AssignmentHint, reference: AssignmentReference) -> tuple[float, tuple[str, ...]]:
    reasons = ["same explicit course"]
    score = 0.10
    if hint.assignment_hint:
        title_score, title_reason = _score_title(hint.assignment_hint, reference)
        score += title_score
        reasons.append(title_reason)

        hint_numbers = _numbers(hint.assignment_hint)
        reference_numbers = set().union(
            *(_numbers(name) for name in (reference.canonical_title, *reference.aliases))
        )
        if hint_numbers and reference_numbers:
            if hint_numbers & reference_numbers:
                score += 0.15
                reasons.append("assignment number agrees")
            else:
                score -= 0.30
                reasons.append("assignment number conflicts")

    if (
        hint.assignment_type
        and reference.assignment_type
        and hint.assignment_type.casefold() == reference.assignment_type.casefold()
    ):
        score += 0.05
        reasons.append("assignment type agrees")
    if hint.candidate_due_at and reference.due_at:
        distance = abs((_utc(hint.candidate_due_at) - _utc(reference.due_at)).total_seconds())
        if distance <= 48 * 3600:
            score += 0.05
            reasons.append("nearby candidate date")
    return max(0.0, min(1.0, score)), tuple(reasons)


def match_assignment(
    hint: AssignmentHint,
    candidates: Iterable[AssignmentReference],
) -> AssignmentMatch:
    """Match only within explicit course context and leave ambiguity unresolved."""

    if hint.course_id is None:
        return AssignmentMatch(None, 0.0, "low", "unresolved", ("course context is required",))
    scoped = [candidate for candidate in candidates if candidate.course_id == hint.course_id]
    if not scoped:
        return AssignmentMatch(None, 0.0, "low", "unresolved", ("no candidates in course",))

    if hint.canvas_assignment_id:
        exact = [
            candidate
            for candidate in scoped
            if candidate.canvas_assignment_id == hint.canvas_assignment_id
        ]
        if len(exact) == 1:
            return AssignmentMatch(
                exact[0].assignment_id,
                1.0,
                "high",
                "matched",
                ("exact Canvas assignment ID in course",),
            )
    if hint.canonical_url:
        exact = [candidate for candidate in scoped if candidate.canonical_url == hint.canonical_url]
        if len(exact) == 1:
            return AssignmentMatch(
                exact[0].assignment_id,
                1.0,
                "high",
                "matched",
                ("exact canonical assignment URL in course",),
            )

    ranked = sorted(
        ((candidate, *_score(hint, candidate)) for candidate in scoped),
        key=lambda item: (item[1], -item[0].assignment_id),
        reverse=True,
    )
    winner, score, reasons = ranked[0]
    alternatives = tuple((candidate.assignment_id, round(value, 4)) for candidate, value, _ in ranked)
    if len(ranked) > 1 and score - ranked[1][1] < AMBIGUITY_MARGIN:
        return AssignmentMatch(
            None,
            round(score, 4),
            "medium" if score >= MEDIUM_MATCH else "low",
            "ambiguous",
            (*reasons, "top course-scoped candidates are too close"),
            alternatives,
        )
    confidence = "high" if score >= HIGH_MATCH else "medium" if score >= MEDIUM_MATCH else "low"
    return AssignmentMatch(
        winner.assignment_id if score >= MEDIUM_MATCH else None,
        round(score, 4),
        confidence,
        "matched" if score >= MEDIUM_MATCH else "unresolved",
        reasons,
        alternatives,
    )
