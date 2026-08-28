"""Evidence-backed academic interpretation boundaries."""

from src.duesoon.intelligence.deadline_resolver import (
    CandidateAssessment,
    DeadlineCandidate,
    DeadlineResolution,
    resolve_deadline,
    source_authority,
)
from src.duesoon.intelligence.matcher import (
    AssignmentHint,
    AssignmentMatch,
    AssignmentReference,
    match_assignment,
    normalize_assignment_title,
)
from src.duesoon.intelligence.evidence import (
    DEADLINE_CLAIM_TYPES,
    deadline_candidate_from_evidence,
    deadline_candidates_from_evidence,
)

__all__ = [
    "AssignmentHint",
    "AssignmentMatch",
    "AssignmentReference",
    "CandidateAssessment",
    "DEADLINE_CLAIM_TYPES",
    "DeadlineCandidate",
    "DeadlineResolution",
    "match_assignment",
    "deadline_candidate_from_evidence",
    "deadline_candidates_from_evidence",
    "normalize_assignment_title",
    "resolve_deadline",
    "source_authority",
]
