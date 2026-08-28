# ADR 0003: Contextual Urgency and Persistent Deadline Evidence

**Status:** Accepted
**Date:** 2026-08-28

## Decision

Use `urgency-v2` as the active deterministic urgency policy. Score time pressure from `operational_due_at`, never directly from raw Canvas `due_at`. The time factor uses a smooth monotonic curve between the reviewed urgency-v1 anchors, preserving the v1 boundary values while avoiding large jumps between them.

Keep the v1 value, submission, and classification concepts, and add bounded context:

- deadline risk contributes at most 10 points for provisional, low-confidence, or conflicted evidence;
- overdue context contributes 2–10 points as incomplete work becomes further overdue;
- nearby-workload pressure accounts for distance within the existing 24-hour window; and
- recent earlier deadline changes expire after the configured awareness window.

Submitted, graded, and cancelled assignments override every factor to zero. All weights, limits, thresholds, and the policy identifier live in validated `UrgencyConfig`; every result records `config_version="urgency-v2"`. AI does not calculate urgency, select deadlines, cross checkpoints, or send reminders.

Persist deadline claims and assignment-evidence links as append-only provenance. Only admitted, validated, timezone-aware evidence can become a scheduling candidate. Resolution applies deterministic authority, matching, recency, explicit supersession, corroboration, and conflict rules. During unresolved credible conflicts, `operational_due_at` is the earliest exact candidate for protective scheduling.

Owner deadline confirmation creates an immutable, assignment- and course-scoped source record, claim, and evidence link. It is idempotent for the same assignment and exact UTC instant, remains inspectable, and does not erase prior evidence. API responses expose safe metadata and explanations, never raw source payloads or private excerpts.

## Consequences

- Urgency remains explainable as a bounded factor breakdown and works without an AI provider.
- Evidence-backed deadlines now drive dashboard views, urgency, reconciliation, and reminders.
- Date-only, malformed, unvalidated, or unresolved evidence cannot create exact checkpoint schedules.
- Completed work cannot retain urgency from conflicts, lateness, value, or workload.
- Rollback to urgency-v1 is a code/config rollback to the prior scoring implementation and `urgency-v1` identifier. Persistent claims, evidence, effective deadlines, reminder deduplication, and submission rechecks remain intact; rollback must rerun the v1 boundary tests before release.
