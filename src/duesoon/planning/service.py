"""Effort/progress evidence resolution and owner planning corrections."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
import re
from statistics import median
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.duesoon.assignments.effective import EffectiveAssignment, project_canvas_assignment
from src.duesoon.intelligence.service import assignment_load_options
from src.duesoon.intelligence.matcher import (
    HIGH_MATCH,
    AssignmentHint,
    AssignmentReference,
    match_assignment,
)
from src.duesoon.persistence.models import (
    Assignment,
    AssignmentCompletionObservation,
    AssignmentEffortEstimate,
    AssignmentProgressObservation,
    CalendarBusyBlock,
)

from .priority import (
    BlockingProjection,
    EffortProjection,
    WorkPriorityBreakdown,
    score_work_priority,
)


TYPE_PRIORS: tuple[tuple[tuple[str, ...], tuple[int, int, int]], ...] = (
    (("capstone", "project", "research paper"), (600, 360, 960)),
    (("exam", "midterm", "test", "final"), (240, 120, 420)),
    (("lab", "report"), (240, 120, 420)),
    (("homework", "challenge", "problem set"), (90, 45, 180)),
    (("discussion",), (60, 30, 90)),
    (("quiz",), (60, 30, 120)),
    (("participation",), (30, 15, 45)),
)

_COUNT_UNITS = (
    "question",
    "module",
    "chapter",
    "page",
    "problem",
    "section",
    "exercise",
)


def parse_completion_feedback(value: str) -> tuple[int | None, dict[str, Any], str]:
    """Extract explicit duration/work-unit facts while preserving the full narrative."""

    text = re.sub(r"\s+", " ", value.strip())
    lowered = text.casefold()
    hours = sum(
        float(match)
        for match in re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr)\b", lowered)
    )
    minutes = sum(
        int(match)
        for match in re.findall(r"\b(\d+)\s*(?:minutes?|mins?|min)\b", lowered)
    )
    if re.search(r"\b(?:1|an?|one)\s+hour\s+and\s+a\s+half\b", lowered):
        if re.search(r"\b1\s+hour\b", lowered):
            hours -= 1
        hours += 1.5
    elif re.search(r"\b(?:an?|one)\s+hour\b", lowered):
        hours += 1
    if re.search(r"\bhalf\s+an?\s+hour\b", lowered):
        hours += 0.5

    duration = round(hours * 60 + minutes) if hours or minutes else None
    features: dict[str, Any] = {}
    if duration is not None:
        features["duration_minutes"] = duration
    elapsed = re.search(r"\b(\d+)\s+days?\b", lowered)
    if elapsed:
        features["elapsed_days"] = int(elapsed.group(1))
    work_units: dict[str, int] = {}
    for amount, unit in re.findall(
        rf"\b(\d+)\s+({'|'.join(f'{item}s?' for item in _COUNT_UNITS)})\b",
        lowered,
    ):
        singular = unit[:-1] if unit.endswith("s") else unit
        work_units[singular] = int(amount)
    if work_units:
        features["work_units"] = work_units
    difficulty = next(
        (label for label in ("very hard", "hard", "difficult", "easy") if label in lowered),
        None,
    )
    if difficulty:
        features["difficulty_signal"] = difficulty
    return duration, features, "structured" if features else "narrative_only"


class PlanningService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def priorities(
        self,
        items: Sequence[EffectiveAssignment],
        now: datetime,
    ) -> dict[int, WorkPriorityBreakdown]:
        capacity = self.capacity_learning()
        learned_hours = (
            capacity["learned_minutes_per_day"] / 60
            if capacity["status"] == "learned"
            else None
        )
        with self.sessions() as session:
            records = session.scalars(
                select(Assignment)
                .options(*assignment_load_options())
                .where(Assignment.id.in_([item.assignment_id for item in items]))
                .order_by(Assignment.id)
            ).all()
            owner_effort = self._latest_effort(session)
            progress = self._latest_progress(session)
            percentiles = self._course_percentiles(records)
            calendar_blocks = self._calendar_blocks(session, items, now)
            efforts = {
                record.id: self._effort_projection(
                    record,
                    owner_effort.get(record.id),
                    progress.get(record.id),
                )
                for record in records
            }
        base = {
            item.assignment_id: score_work_priority(
                item,
                items,
                efforts.get(item.assignment_id, EffortProjection.unknown()),
                now,
                course_value_percentile=percentiles.get(item.assignment_id),
                usable_hours_per_day=learned_hours,
                calendar_blocked_minutes=self._blocked_minutes(
                    calendar_blocks, now, item.operational_due_at
                ),
            )
            for item in items
        }
        blocking = self._blocking_context(records, items, base)
        return {
            item.assignment_id: score_work_priority(
                item,
                items,
                efforts.get(item.assignment_id, EffortProjection.unknown()),
                now,
                course_value_percentile=percentiles.get(item.assignment_id),
                usable_hours_per_day=learned_hours,
                calendar_blocked_minutes=self._blocked_minutes(
                    calendar_blocks, now, item.operational_due_at
                ),
                blocking=blocking.get(item.assignment_id),
            )
            for item in items
        }

    def inspect(self, assignment_id: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.sessions() as session:
            records = session.scalars(
                select(Assignment)
                .options(*assignment_load_options())
                .order_by(Assignment.id)
            ).all()
            selected = next((item for item in records if item.id == assignment_id), None)
            if selected is None:
                raise LookupError("assignment not found")
            items = tuple(project_canvas_assignment(item) for item in records)
            effort_rows = session.scalars(
                select(AssignmentEffortEstimate)
                .where(AssignmentEffortEstimate.assignment_id == assignment_id)
                .order_by(AssignmentEffortEstimate.created_at, AssignmentEffortEstimate.id)
            ).all()
            progress_rows = session.scalars(
                select(AssignmentProgressObservation)
                .where(AssignmentProgressObservation.assignment_id == assignment_id)
                .order_by(
                    AssignmentProgressObservation.created_at,
                    AssignmentProgressObservation.id,
                )
            ).all()
            completion_rows = session.scalars(
                select(AssignmentCompletionObservation)
                .where(AssignmentCompletionObservation.assignment_id == assignment_id)
                .order_by(
                    AssignmentCompletionObservation.created_at,
                    AssignmentCompletionObservation.id,
                )
            ).all()
            effort = self._effort_projection(
                selected,
                effort_rows[-1] if effort_rows else None,
                progress_rows[-1] if progress_rows else None,
            )
        priority = self.priorities(items, now)[assignment_id]
        latest_completion = completion_rows[-1] if completion_rows else None
        return {
            "assignment_id": assignment_id,
            "effort": {
                "estimated_minutes": effort.estimated_minutes,
                "lower_minutes": effort.lower_minutes,
                "upper_minutes": effort.upper_minutes,
                "remaining_minutes": effort.remaining_minutes,
                "confidence": effort.confidence,
                "source": effort.source,
                "evidence_ids": list(effort.evidence_ids),
            },
            "progress_percent": effort.progress_percent,
            "priority": priority.to_dict(),
            "effort_history_count": len(effort_rows),
            "progress_history_count": len(progress_rows),
            "completion_feedback_count": len(completion_rows),
            "latest_completion_feedback": (
                {
                    "duration_minutes": latest_completion.duration_minutes,
                    "features": latest_completion.extracted_features,
                    "parsing_status": latest_completion.parsing_status,
                }
                if latest_completion else None
            ),
            "protections": {
                "changes_deadline": False,
                "changes_urgency": False,
                "changes_reminders": False,
            },
        }

    def record_owner_update(
        self,
        assignment_id: int,
        *,
        estimated_minutes: int | None = None,
        percent_complete: int | None = None,
        completion_feedback: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        clean_feedback = completion_feedback.strip()[:5000] if completion_feedback else None
        if estimated_minutes is None and percent_complete is None and not clean_feedback:
            raise ValueError("effort, progress, or completion feedback is required")
        if estimated_minutes is not None and not 5 <= estimated_minutes <= 10_080:
            raise ValueError("estimated minutes must be between 5 and 10080")
        if percent_complete is not None and not 0 <= percent_complete <= 100:
            raise ValueError("progress percent must be between 0 and 100")
        clean_note = note.strip()[:2000] if note and note.strip() else None
        parsed_duration = None
        parsed_features: dict[str, Any] = {}
        parsing_status = "narrative_only"
        if clean_feedback:
            parsed_duration, parsed_features, parsing_status = parse_completion_feedback(
                clean_feedback
            )
        with self.sessions() as session:
            if session.get(Assignment, assignment_id) is None:
                raise LookupError("assignment not found")
            if estimated_minutes is not None:
                session.add(
                    AssignmentEffortEstimate(
                        assignment_id=assignment_id,
                        estimated_minutes=estimated_minutes,
                        lower_minutes=estimated_minutes,
                        upper_minutes=estimated_minutes,
                        confidence="high",
                        source_kind="owner_confirmed",
                        evidence_id=None,
                        owner_confirmed=True,
                        note=clean_note,
                    )
                )
            elif parsed_duration is not None:
                session.add(
                    AssignmentEffortEstimate(
                        assignment_id=assignment_id,
                        estimated_minutes=parsed_duration,
                        lower_minutes=parsed_duration,
                        upper_minutes=parsed_duration,
                        confidence="high",
                        source_kind="owner_completion_feedback",
                        evidence_id=None,
                        owner_confirmed=True,
                        note=clean_feedback,
                    )
                )
            if percent_complete is not None:
                session.add(
                    AssignmentProgressObservation(
                        assignment_id=assignment_id,
                        percent_complete=percent_complete,
                        source_kind="owner",
                        note=clean_note,
                    )
                )
            if clean_feedback:
                session.add(
                    AssignmentCompletionObservation(
                        assignment_id=assignment_id,
                        feedback_text=clean_feedback,
                        duration_minutes=parsed_duration,
                        extracted_features=parsed_features,
                        parsing_status=parsing_status,
                    )
                )
            session.commit()
        return self.inspect(assignment_id)

    def capacity_learning(self) -> dict[str, Any]:
        """Infer conservative school-work pace from confirmed completed outcomes."""

        with self.sessions() as session:
            assignments = session.scalars(
                select(Assignment)
                .options(selectinload(Assignment.submission))
                .order_by(Assignment.id)
            ).all()
            effort_rows = session.scalars(
                select(AssignmentEffortEstimate)
                .where(AssignmentEffortEstimate.owner_confirmed.is_(True))
                .order_by(
                    AssignmentEffortEstimate.assignment_id,
                    AssignmentEffortEstimate.created_at,
                    AssignmentEffortEstimate.id,
                )
            ).all()
            progress_rows = session.scalars(
                select(AssignmentProgressObservation).order_by(
                    AssignmentProgressObservation.assignment_id,
                    AssignmentProgressObservation.created_at,
                    AssignmentProgressObservation.id,
                )
            ).all()
        efforts = {row.assignment_id: row for row in effort_rows}
        progress: dict[int, list[AssignmentProgressObservation]] = {}
        for row in progress_rows:
            progress.setdefault(row.assignment_id, []).append(row)
        samples: list[tuple[int, int]] = []
        for assignment in assignments:
            submission = assignment.submission
            effort = efforts.get(assignment.id)
            if (
                submission is None
                or submission.normalized_status.casefold() not in {"submitted", "graded"}
                or submission.submitted_at is None
                or effort is None
            ):
                continue
            submitted_at = _utc(submission.submitted_at)
            observations = [
                row
                for row in progress.get(assignment.id, [])
                if row.percent_complete < 100 and _utc(row.created_at) < submitted_at
            ]
            if not observations:
                continue
            observation = observations[-1]
            elapsed_days = max(
                1,
                ceil((submitted_at - _utc(observation.created_at)).total_seconds() / 86400),
            )
            remaining = ceil(
                effort.estimated_minutes * (100 - observation.percent_complete) / 100
            )
            samples.append((assignment.id, max(1, round(remaining / elapsed_days))))

        enough = len(samples) >= 3
        return {
            "status": "learned" if enough else "insufficient_evidence",
            "sample_count": len(samples),
            "learned_minutes_per_day": (
                round(median(value for _, value in samples)) if enough else None
            ),
            "confidence": "high" if len(samples) >= 6 else "medium" if enough else "low",
            "method": "median_confirmed_remaining_effort_per_day",
            "evidence_ids": [f"capacity-outcome:{assignment_id}" for assignment_id, _ in samples],
            "affects_deadlines": False,
            "affects_reminders": False,
        }

    def learning_questions(self, *, limit: int = 3) -> list[dict[str, Any]]:
        """Ask for missing effort only after Canvas records completion."""

        with self.sessions() as session:
            owner_effort_ids = set(
                session.scalars(
                    select(AssignmentEffortEstimate.assignment_id).where(
                        AssignmentEffortEstimate.owner_confirmed.is_(True)
                    )
                ).all()
            )
            assignments = session.scalars(
                select(Assignment)
                .options(
                    selectinload(Assignment.course),
                    selectinload(Assignment.submission),
                )
                .order_by(Assignment.id.desc())
            ).all()
            eligible = [
                item
                for item in assignments
                if item.id not in owner_effort_ids
                and item.submission is not None
                and item.submission.normalized_status.casefold() in {"submitted", "graded"}
                and item.submission.submitted_at is not None
            ]
            eligible.sort(
                key=lambda item: (_utc(item.submission.submitted_at), item.id),
                reverse=True,
            )
            return [
                {
                    "assignment_id": item.id,
                    "title": item.canonical_title,
                    "course_name": item.course.name,
                    "prompt": f"Describe the time, size, difficulty, and blockers for {item.canonical_title}.",
                }
                for item in eligible[: max(1, min(limit, 10))]
            ]

    @staticmethod
    def _latest_effort(session: Session) -> dict[int, AssignmentEffortEstimate]:
        rows = session.scalars(
            select(AssignmentEffortEstimate).order_by(
                AssignmentEffortEstimate.assignment_id,
                AssignmentEffortEstimate.created_at,
                AssignmentEffortEstimate.id,
            )
        ).all()
        return {item.assignment_id: item for item in rows}

    @staticmethod
    def _latest_progress(session: Session) -> dict[int, AssignmentProgressObservation]:
        rows = session.scalars(
            select(AssignmentProgressObservation).order_by(
                AssignmentProgressObservation.assignment_id,
                AssignmentProgressObservation.created_at,
                AssignmentProgressObservation.id,
            )
        ).all()
        return {item.assignment_id: item for item in rows}

    @staticmethod
    def _effort_projection(
        assignment: Assignment,
        owner: AssignmentEffortEstimate | None,
        progress: AssignmentProgressObservation | None,
    ) -> EffortProjection:
        progress_percent = progress.percent_complete if progress else 0
        if owner is not None:
            remaining = ceil(owner.estimated_minutes * (100 - progress_percent) / 100)
            return EffortProjection(
                owner.estimated_minutes,
                owner.lower_minutes,
                owner.upper_minutes,
                remaining,
                progress_percent,
                owner.confidence,
                owner.source_kind,
                (f"owner-effort:{owner.id}",),
                (() if progress else ("No progress update exists; all estimated effort remains.",)),
            )

        evidence = PlanningService._workload_evidence(assignment)
        if evidence is not None:
            estimate, lower, upper, evidence_id, confidence = evidence
            remaining = ceil(estimate * (100 - progress_percent) / 100)
            return EffortProjection(
                estimate,
                lower,
                upper,
                remaining,
                progress_percent,
                confidence,
                "validated_workload_evidence",
                (evidence_id,),
                (() if progress else ("No progress update exists; all estimated effort remains.",)),
            )

        text = f"{assignment.assignment_type or ''} {assignment.canonical_title}".casefold()
        prior = next((value for words, value in TYPE_PRIORS if any(word in text for word in words)), None)
        if prior is None:
            return EffortProjection.unknown()
        estimate, lower, upper = prior
        remaining = ceil(estimate * (100 - progress_percent) / 100)
        return EffortProjection(
            estimate,
            lower,
            upper,
            remaining,
            progress_percent,
            "low",
            "assignment_type_prior",
            (),
            (
                "Low-confidence assignment-type prior; owner correction or validated workload evidence should replace it.",
                *(() if progress else ("No progress update exists; all estimated effort remains.",)),
            ),
        )

    @staticmethod
    def _workload_evidence(
        assignment: Assignment,
    ) -> tuple[int, int, int, str, str] | None:
        candidates = []
        for link in assignment.evidence:
            claim = link.claim
            if (
                link.disposition != "admitted"
                or claim.validation_status != "validated"
                or claim.claim_type != "workload_hint"
            ):
                continue
            value = claim.normalized_value
            if not isinstance(value, dict):
                continue
            estimate = value.get("estimated_minutes")
            lower = value.get("lower_minutes", estimate)
            upper = value.get("upper_minutes", estimate)
            if not all(isinstance(item, int) and 5 <= item <= 10_080 for item in (estimate, lower, upper)):
                continue
            if not lower <= estimate <= upper:
                continue
            candidates.append((
                link.authority_score,
                claim.extraction_confidence,
                estimate,
                lower,
                upper,
                f"assignment-evidence:{link.id}:claim:{claim.id}",
            ))
        if not candidates:
            return None
        authority, extraction, estimate, lower, upper, evidence_id = max(candidates)
        confidence = "high" if authority >= 0.9 and extraction >= 0.85 else "medium"
        return estimate, lower, upper, evidence_id, confidence

    @staticmethod
    def _course_percentiles(records: Sequence[Assignment]) -> dict[int, float]:
        grouped: dict[int, list[Assignment]] = {}
        for item in records:
            if item.points_possible is not None and item.points_possible >= 0:
                grouped.setdefault(item.course_id, []).append(item)
        values: dict[int, float] = {}
        for course_items in grouped.values():
            ordered = sorted(course_items, key=lambda item: (item.points_possible, item.id))
            if len(ordered) == 1:
                values[ordered[0].id] = 0.5
                continue
            for index, item in enumerate(ordered):
                values[item.id] = index / (len(ordered) - 1)
        return values

    @staticmethod
    def _blocking_context(
        records: Sequence[Assignment],
        items: Sequence[EffectiveAssignment],
        base: dict[int, WorkPriorityBreakdown],
    ) -> dict[int, BlockingProjection]:
        """Resolve admitted prerequisite claims within one course; ambiguity has no effect."""

        item_by_id = {item.assignment_id: item for item in items}
        references = tuple(
            AssignmentReference(
                assignment_id=record.id,
                course_id=record.course_id,
                canonical_title=record.canonical_title,
                canvas_assignment_id=record.canvas_assignment_id,
                canonical_url=record.html_url,
                assignment_type=record.assignment_type,
                due_at=record.canvas_due_at,
            )
            for record in records
        )
        relations: dict[int, dict[int, str]] = {}
        for dependent in records:
            projected = item_by_id.get(dependent.id)
            if projected is None or projected.submission_status.casefold() in {"submitted", "graded", "cancelled"}:
                continue
            for link in dependent.evidence:
                claim = link.claim
                if (
                    link.disposition != "admitted"
                    or claim.validation_status != "validated"
                    or claim.claim_type != "prerequisite_relationship"
                    or not isinstance(claim.normalized_value, dict)
                ):
                    continue
                hint = claim.normalized_value.get("prerequisite_assignment_hint")
                if not isinstance(hint, str) or not hint.strip():
                    continue
                match = match_assignment(
                    AssignmentHint(
                        course_id=dependent.course_id,
                        assignment_hint=hint.strip(),
                    ),
                    references,
                )
                if (
                    match.assignment_id is None
                    or match.assignment_id == dependent.id
                    or match.score < HIGH_MATCH
                ):
                    continue
                relations.setdefault(match.assignment_id, {})[dependent.id] = (
                    f"assignment-evidence:{link.id}:claim:{claim.id}"
                )
        return {
            prerequisite_id: BlockingProjection(
                dependent_count=len(dependents),
                highest_dependent_score=max(
                    base[dependent_id].total
                    for dependent_id in dependents
                    if dependent_id in base
                ),
                evidence_ids=tuple(dependents.values()),
            )
            for prerequisite_id, dependents in relations.items()
            if any(dependent_id in base for dependent_id in dependents)
        }

    @staticmethod
    def _calendar_blocks(
        session: Session,
        items: Sequence[EffectiveAssignment],
        now: datetime,
    ) -> tuple[CalendarBusyBlock, ...]:
        due_values = [
            _utc(item.operational_due_at)
            for item in items
            if item.operational_due_at is not None and _utc(item.operational_due_at) > _utc(now)
        ]
        if not due_values:
            return ()
        return tuple(
            session.scalars(
                select(CalendarBusyBlock).where(
                    CalendarBusyBlock.active.is_(True),
                    CalendarBusyBlock.ends_at > _utc(now),
                    CalendarBusyBlock.starts_at < max(due_values),
                )
            ).all()
        )

    @staticmethod
    def _blocked_minutes(
        rows: Sequence[CalendarBusyBlock],
        start: datetime,
        end: datetime | None,
    ) -> int:
        if end is None or _utc(end) <= _utc(start):
            return 0
        left, right = _utc(start), _utc(end)
        intervals = sorted(
            (
                max(left, _utc(row.starts_at)),
                min(right, _utc(row.ends_at)),
            )
            for row in rows
            if _utc(row.ends_at) > left and _utc(row.starts_at) < right
        )
        merged: list[tuple[datetime, datetime]] = []
        for interval_start, interval_end in intervals:
            if not merged or interval_start > merged[-1][1]:
                merged.append((interval_start, interval_end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], interval_end))
        return round(
            sum((interval_end - interval_start).total_seconds() for interval_start, interval_end in merged)
            / 60
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
