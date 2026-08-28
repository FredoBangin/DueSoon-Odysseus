"""Deterministic deadline evidence fusion.

Untrusted text must be converted to validated claims before it reaches this
module. The resolver only applies explicit, versioned policy to structured
deadline candidates. It never calls a model or sends a reminder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable


MATERIAL_DIFFERENCE_SECONDS = 15 * 60
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.65
CONFLICT_CREDIBILITY = 0.78
CONFLICT_MARGIN = 0.12

SOURCE_AUTHORITY: dict[str, float] = {
    "professor_email_correction": 1.00,
    "canvas_inbox_correction": 1.00,
    "course_announcement": 0.97,
    "canvas_assignment": 0.95,
    "assignment_instructions": 0.92,
    "syllabus": 0.85,
    "instructor_document": 0.82,
    "canvas_module": 0.75,
    "historical_pattern": 0.45,
    "student_note": 0.25,
}


def source_authority(source_kind: str) -> float:
    """Return configured authority for a known evidence source."""

    try:
        return SOURCE_AUTHORITY[source_kind]
    except KeyError as exc:
        raise ValueError(f"unknown deadline source kind: {source_kind}") from exc


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class DeadlineCandidate:
    """One validated deadline claim plus deterministic resolution features."""

    evidence_id: str
    due_at: datetime
    source_kind: str
    published_at: datetime | None
    authority: float
    course_match: float = 1.0
    assignment_match: float = 1.0
    explicitness: float = 1.0
    precision: str = "exact_datetime"
    explicit_correction: bool = False
    user_confirmed: bool = False
    author_verified: bool = True
    source_current: bool = True
    extraction_reliability: float = 1.0
    timezone_certainty: float = 1.0
    supersedes_evidence_ids: tuple[str, ...] = ()
    independence_key: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must not be empty")
        if self.precision not in {"exact_datetime", "date_only", "relative", "unknown"}:
            raise ValueError("unsupported deadline precision")
        for name in (
            "authority",
            "course_match",
            "assignment_match",
            "explicitness",
            "extraction_reliability",
            "timezone_certainty",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    @property
    def quality(self) -> float:
        precision_score = {
            "exact_datetime": 1.0,
            "date_only": 0.65,
            "relative": 0.45,
            "unknown": 0.0,
        }[self.precision]
        score = (
            self.authority * 0.30
            + self.course_match * 0.15
            + self.assignment_match * 0.25
            + self.explicitness * 0.10
            + precision_score * 0.05
            + self.extraction_reliability * 0.10
            + self.timezone_certainty * 0.05
        )
        if not self.source_current:
            score -= 0.10
        return max(0.0, min(1.0, score))

    @property
    def provenance_key(self) -> str:
        return self.independence_key or self.evidence_id


@dataclass(frozen=True)
class CandidateAssessment:
    evidence_id: str
    due_at: datetime
    quality: float
    admissible: bool
    reason: str


@dataclass(frozen=True)
class DeadlineResolution:
    effective_due_at: datetime | None
    operational_due_at: datetime | None
    status: str
    confidence: str
    evidence_ids: tuple[str, ...]
    source_summary: str
    explanation: str
    precision: str = "unknown"
    conflicting_due_at: tuple[datetime, ...] = ()
    assessments: tuple[CandidateAssessment, ...] = ()


def _assessment(candidate: DeadlineCandidate) -> CandidateAssessment:
    reasons: list[str] = []
    if not candidate.source_current:
        reasons.append("source version is not current")
    if candidate.course_match < MEDIUM_CONFIDENCE:
        reasons.append("course match is below 0.65")
    if candidate.assignment_match < MEDIUM_CONFIDENCE:
        reasons.append("assignment match is below 0.65")
    if candidate.quality < MEDIUM_CONFIDENCE:
        reasons.append("combined evidence quality is below 0.65")
    if candidate.precision != "exact_datetime":
        reasons.append("deadline lacks exact date, time, or timezone precision")
    return CandidateAssessment(
        evidence_id=candidate.evidence_id,
        due_at=_utc(candidate.due_at),
        quality=round(candidate.quality, 4),
        admissible=not reasons,
        reason="; ".join(reasons) if reasons else "admissible exact deadline evidence",
    )


def _published(candidate: DeadlineCandidate) -> datetime:
    return _utc(candidate.published_at) if candidate.published_at else datetime.min.replace(tzinfo=UTC)


def _same_deadline(left: datetime, right: datetime) -> bool:
    return abs((_utc(left) - _utc(right)).total_seconds()) <= MATERIAL_DIFFERENCE_SECONDS


def _group_strength(items: list[DeadlineCandidate]) -> float:
    independent_sources = len({item.provenance_key for item in items})
    corroboration = min(0.08, 0.025 * max(0, independent_sources - 1))
    return min(1.0, max(item.quality for item in items) + corroboration)


def _supporting_ids(items: Iterable[DeadlineCandidate]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.evidence_id for item in items))


def _resolved(
    winner: DeadlineCandidate,
    supporting: Iterable[DeadlineCandidate],
    explanation: str,
    assessments: tuple[CandidateAssessment, ...],
) -> DeadlineResolution:
    due = _utc(winner.due_at)
    agreeing = [item for item in supporting if _same_deadline(item.due_at, due)]
    return DeadlineResolution(
        effective_due_at=due,
        operational_due_at=due,
        status="resolved",
        confidence="high",
        evidence_ids=_supporting_ids(agreeing) or (winner.evidence_id,),
        source_summary=f"Resolved from {winner.source_kind}",
        explanation=explanation,
        precision=winner.precision,
        assessments=assessments,
    )


def resolve_deadline(candidates: Iterable[DeadlineCandidate]) -> DeadlineResolution:
    """Resolve structured claims using authority, recency, and supersession policy."""

    candidate_list = list(candidates)
    assessments = tuple(_assessment(candidate) for candidate in candidate_list)
    exact = [
        candidate
        for candidate, assessment in zip(candidate_list, assessments, strict=True)
        if assessment.admissible
    ]

    if not exact:
        imprecise = [
            candidate
            for candidate in candidate_list
            if candidate.source_current
            and candidate.precision in {"date_only", "relative"}
            and candidate.course_match >= MEDIUM_CONFIDENCE
            and candidate.assignment_match >= MEDIUM_CONFIDENCE
            and candidate.quality >= MEDIUM_CONFIDENCE
        ]
        if imprecise:
            winner = max(imprecise, key=lambda item: (item.quality, _published(item)))
            return DeadlineResolution(
                effective_due_at=_utc(winner.due_at),
                operational_due_at=None,
                status="provisional",
                confidence="medium",
                evidence_ids=(winner.evidence_id,),
                source_summary=f"Provisional date from {winner.source_kind}",
                explanation=(
                    "Evidence identifies a likely date but lacks exact scheduling precision; "
                    "checkpoint reminders are withheld."
                ),
                precision=winner.precision,
                assessments=assessments,
            )
        return DeadlineResolution(
            effective_due_at=None,
            operational_due_at=None,
            status="unknown",
            confidence="low",
            evidence_ids=(),
            source_summary="No admissible deadline evidence",
            explanation="No validated evidence is precise and well matched enough to schedule.",
            assessments=assessments,
        )

    confirmed = [candidate for candidate in exact if candidate.user_confirmed]
    if confirmed:
        winner = max(confirmed, key=_published)
        return _resolved(
            winner,
            confirmed,
            "Newest owner-confirmed deadline evidence wins while prior evidence remains preserved.",
            assessments,
        )

    corrections = [
        candidate
        for candidate in exact
        if candidate.explicit_correction
        and candidate.author_verified
        and candidate.published_at is not None
        and candidate.authority >= HIGH_CONFIDENCE
        and candidate.assignment_match >= HIGH_CONFIDENCE
        and candidate.course_match >= HIGH_CONFIDENCE
        and candidate.explicitness >= HIGH_CONFIDENCE
    ]
    for winner in sorted(corrections, key=_published, reverse=True):
        older_conflicts = [
            candidate
            for candidate in exact
            if candidate.evidence_id != winner.evidence_id
            and not _same_deadline(candidate.due_at, winner.due_at)
            and (
                _published(candidate) < _published(winner)
                or candidate.evidence_id in winner.supersedes_evidence_ids
            )
        ]
        later_equal_or_stronger = [
            candidate
            for candidate in exact
            if candidate.evidence_id != winner.evidence_id
            and not _same_deadline(candidate.due_at, winner.due_at)
            and _published(candidate) > _published(winner)
            and candidate.quality >= winner.quality
        ]
        if older_conflicts and not later_equal_or_stronger:
            agreeing = [candidate for candidate in exact if _same_deadline(candidate.due_at, winner.due_at)]
            return _resolved(
                winner,
                agreeing,
                "Newest explicit, verified correction supersedes older conflicting evidence.",
                assessments,
            )

    groups: list[list[DeadlineCandidate]] = []
    for candidate in sorted(exact, key=lambda item: _utc(item.due_at)):
        group = next(
            (items for items in groups if _same_deadline(items[0].due_at, candidate.due_at)),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    ranked = sorted(
        groups,
        key=lambda items: (_group_strength(items), max(_published(item) for item in items)),
        reverse=True,
    )
    winning_group = ranked[0]
    winner = max(winning_group, key=lambda item: (item.quality, _published(item)))
    winner_strength = _group_strength(winning_group)

    if len(ranked) > 1:
        runner_group = ranked[1]
        runner_strength = _group_strength(runner_group)
        runner = max(runner_group, key=lambda item: item.quality)
        if runner_strength >= CONFLICT_CREDIBILITY and winner_strength - runner_strength < CONFLICT_MARGIN:
            credible = [
                item
                for group in ranked
                for item in group
                if item.quality >= CONFLICT_CREDIBILITY
            ]
            dates = tuple(sorted({_utc(item.due_at) for item in credible}))
            return DeadlineResolution(
                effective_due_at=_utc(winner.due_at),
                operational_due_at=min(dates),
                status="conflicted",
                confidence="medium",
                evidence_ids=_supporting_ids(credible),
                source_summary="Credible deadline evidence conflicts",
                explanation=(
                    f"{winner.source_kind} and {runner.source_kind} provide materially different "
                    "credible dates; protective scheduling uses the earliest exact candidate."
                ),
                precision="exact_datetime",
                conflicting_due_at=dates,
                assessments=assessments,
            )

    confidence = "high" if winner_strength >= HIGH_CONFIDENCE else "medium"
    return DeadlineResolution(
        effective_due_at=_utc(winner.due_at),
        operational_due_at=_utc(winner.due_at),
        status="resolved" if confidence == "high" else "provisional",
        confidence=confidence,
        evidence_ids=_supporting_ids(winning_group),
        source_summary=f"Resolved from {winner.source_kind}",
        explanation=(
            "Best corroborated admissible deadline evidence selected; lower-quality "
            "contradictions remain preserved in candidate assessments."
        ),
        precision=winner.precision,
        assessments=assessments,
    )
