# DueSoon Core Backend Completion Plan

**Status:** Approved direction; implementation pending
**Date:** 2026-08-28
**Foundation:** `DUESOON_CODEX_CONTEXT.md`
**Decision record:** `docs/architecture/0006-dual-priority-assistant-autonomy.md`

## 1. Outcome

Complete the academic-intelligence backend without weakening the production Canvas scheduler or
ntfy delivery path. DueSoon must determine both immediate deadline risk and what work should begin
now, cross-reference all connected academic evidence, answer general questions through a bounded
assistant, learn safely, and explain every material decision.

## 2. Proven Baseline

Already working:

- Canvas courses, assignments, submissions, Inbox, announcements, modules, pages, and metadata
  ingestion;
- SQLite persistence on the Azure managed disk;
- `EffectiveAssignment`, deadline evidence storage, deterministic resolver, and owner confirmation;
- `urgency-v2`, checkpoint crossing, deadline-version reconciliation, adaptive reminders,
  database deduplication, and immediate Canvas submission recheck;
- private ntfy delivery, owner web authentication, model routing, learning-review records, Notes,
  Memory, Documents, Gmail/Google Calendar client foundations, and Azure deployment;
- focused DueSoon test suite and healthy single-scheduler production runtime.

Material gaps:

- stored Canvas communications and course content do not yet flow through an automatic
  source-to-claim extraction and assignment-matching pipeline;
- urgency is incorrectly being used as dashboard work priority;
- effort, start-by time, slack, prerequisites, course-relative value, and progress are not modeled;
- model assistant context is a bounded briefing snapshot, not an orchestrated cross-source retrieval
  path for arbitrary questions;
- Gmail and documents do not yet become validated evidence automatically;
- automatic low-risk learning and decision traces are incomplete;
- operational health lacks complete extraction, conflict, scheduler-lag, and learning metrics.

## 3. Non-Negotiable Boundaries

- `operational_due_at` drives urgency and reminders.
- Work priority never changes canonical deadlines or reminder checkpoints.
- AI extracts, estimates, matches, retrieves, and explains; deterministic code validates and owns
  state transitions, scores, scheduling, delivery, and authorization.
- Every live reminder immediately rechecks Canvas submission state.
- Existing checkpoint crossing, deduplication, dry-run behavior, audit history, and single scheduler
  remain intact.
- Course content is untrusted data and cannot issue agent instructions or gain tools.
- Connected academic applications are read-only until an explicit future write capability is
  separately designed and approved.
- No hidden chain-of-thought is exposed. Decision traces contain verifiable evidence and concise
  rationale only.

## 4. Phase A: Measurement and Current-State Proof

1. Add a privacy-safe backend diagnostics projection for score distributions, missing factors,
   evidence coverage, unresolved claims, sync age, and scheduler lag.
2. Capture a scrubbed production calibration snapshot before changing policy.
3. Add regression fixtures representing the owner's current assignment patterns: paired weekly
   work, large distant projects, short near quizzes, missing work, conflicts, and completed items.

Exit criteria:

- current behavior can be reproduced without production secrets or academic text;
- each collapsed LOW result has an explicit missing-factor explanation; and
- no product logic changes have occurred yet.

## 5. Phase B: Work Priority v1

Add a separate deterministic `WorkPriorityBreakdown` and leave `urgency-v2` unchanged.

Initial inputs:

- operational deadline and time remaining;
- estimated effort with confidence and provenance;
- remaining effort after confirmed progress;
- schedule buffer;
- usable available time after known sleep, classes, work, and calendar blocks;
- slack (`usable available time - remaining effort - buffer`);
- course-relative assignment value rather than raw points alone;
- nearby workload and overlapping effort demand;
- assignment type and prerequisite/blocking relationships;
- recent explicit instructor workload or importance evidence; and
- bounded historical completion behavior when enough data exists.

Outputs:

```text
work_priority_score: 0..100
work_priority_band: NOW | NEXT | LATER | MONITOR
start_by_at
slack_minutes
estimated_effort_minutes
effort_confidence: high | medium | low
factor_breakdown
reasons[]
config_version
evidence_ids[]
```

Rules:

- negative or near-zero slack ranks first;
- large distant work may outrank small near work when start-by risk is worse;
- missing deadline/effort data lowers confidence instead of inventing precision;
- missing schedule/calendar data uses visible fallback assumptions and lowers confidence;
- submitted, graded, cancelled, or owner-dismissed work cannot rank as active;
- tie-breaking is deterministic and stable;
- urgency continues to control reminder escalation; priority controls dashboard ordering and
  assistant planning answers.

Exit criteria:

- the large-project-versus-small-quiz scenario ranks by slack;
- every result has a factor breakdown and evidence references;
- old urgency and reminder regression tests remain unchanged and green.

## 6. Phase C: Effort and Progress Evidence

1. Add additive schema fields/tables for effort estimates, progress observations, start-by output,
   decision version, confidence, provenance, and owner corrections.
2. Derive deterministic assignment type and course-relative point percentile where possible.
3. Add structured AI extraction for workload hints and prerequisite relationships.
4. Let the owner correct effort or progress from the Review path.
5. Record predicted versus actual completion timing for later calibration.

Automatic learning may update future course-scoped effort priors only after retaining the old value,
supporting outcomes, model/policy version, confidence, and reversal record.

Exit criteria:

- estimates are traceable and reversible;
- unsupported AI output is rejected;
- unknown effort never becomes a false exact estimate; and
- progress/effort changes recompute priority without touching reminders.

## 7. Phase D: Automatic Academic Evidence Pipeline

Build an idempotent pipeline:

```text
SourceRecord -> normalized text -> structured claims -> validation
-> course-scoped assignment matching -> AssignmentEvidence
-> deadline/effort/prerequisite resolution -> EffectiveAssignment/priority recomputation
```

Sources, in order:

1. Canvas assignment instructions and pages;
2. Canvas Inbox and announcements;
3. modules and module items;
4. supported course files and documents;
5. read-only professor Gmail;
6. owner Notes/Memory as low-authority context.

Required safeguards:

- immutable source versions and claim fingerprints;
- schema-constrained extraction with quoted span/locator;
- same-course candidate bounds before semantic matching;
- prompt-injection isolation and no model tools during extraction;
- confidence thresholds and unresolved review queue;
- authority, recency, corroboration, supersession, precision, and conflict policy;
- incremental processing so unchanged content does not consume model calls.

Exit criteria:

- an explicit professor deadline correction safely changes effective state with provenance;
- ambiguous claims remain unresolved;
- a workload warning can affect effort/priority but not canonical deadline by itself;
- repeat sync creates no duplicate sources, claims, links, events, or reminders.

## 8. Phase E: General, School-Specialized Assistant

Replace scripted intent dependence with a bounded orchestration layer:

1. Classify whether deterministic status tools can answer exactly.
2. Build a minimal question-specific retrieval plan.
3. Query authorized read-only sources only.
4. Identify missing application/permission instead of pretending context exists.
5. Send structured facts and minimal excerpts to the configured primary model.
6. Use fallbacks only for allowed availability failures.
7. Validate citations and remove unsupported factual claims.
8. Return answer plus decision trace.

The assistant may answer general safe questions using the configured model. Academic questions gain
DueSoon retrieval, evidence, priority, deadline, submission, and reminder tools. It receives no
arbitrary shell, filesystem, database-write, secret, email-send, Canvas-write, or unrestricted web
tool.

Decision trace fields:

```text
sources_consulted[]
evidence_ids[]
assumptions[]
confidence_band
deterministic_calculations[]
app_tool_activity[]
missing_connections[]
learning_changes[]
alternative_summary
policy_versions[]
```

Exit criteria:

- arbitrary general questions receive model answers when configured;
- school questions cross-reference all relevant connected sources;
- missing access produces an exact connection request;
- model outage falls back to deterministic academic answers;
- no answer can mutate protected academic state.

## 9. Phase F: Autonomous, Reversible Learning

Automatic low-risk categories:

- answer format and reminder explanation preferences;
- course-scoped assignment aliases;
- effort estimates and type-specific effort priors;
- user-corrected planning assumptions.

Review-required categories:

- deadlines and deadline precision;
- submission status;
- reminder timing or suppression policy;
- professor identity;
- source authority/reliability;
- any cross-course alias or broad behavioral rule.

Every automatic learning action must create an append-only audit record, retain before/after state,
identify evidence/outcome inputs, include confidence and policy/model version, expose it in Review,
and support undo without deleting history.

Exit criteria:

- owner can inspect and undo every learned change;
- automatic learning is limited to its allowlist;
- repeated feedback converges without duplicate proposals or oscillation tests failing.

## 10. Phase G: Integrations and Document Safety

1. Complete read-only Gmail OAuth/token lifecycle and professor/course scoping.
2. Ingest selected Gmail messages and safe attachment metadata into `SourceRecord`.
3. Add bounded PDF, DOCX, HTML, and text extraction with size/type limits and locator provenance.
4. Add Google Calendar as read-only schedule context; it may reduce available planning time but
   cannot define an academic deadline.
5. Add a connection-status registry used by Settings and assistant missing-access responses.

Exit criteria:

- integrations use least privilege and encrypted/protected token storage;
- malicious document instructions remain inert;
- duplicate messages/files remain idempotent;
- revoking an integration stops access without corrupting existing audit history.

## 11. Phase H: Reminder and Operations Completion

1. Add scheduler watermark/lag, Canvas recheck, conflict, extraction, and delivery health metrics.
2. Complete transient/permanent/ambiguous ntfy failure handling and provider reconciliation.
3. Verify downtime catch-up sends at most one message and never bursts historical checkpoints.
4. Add quiet hours and owner frequency caps only after explicit owner configuration.
5. Exercise backup/restore and forward migration on a production-copy fixture.

Exit criteria:

- restart, downtime, provider timeout, and deadline-change end-to-end tests pass;
- exactly one scheduler is observable in production;
- every reminder explains send/suppress decision and relevant policy versions.

## 12. Delivery Order

1. Phase A measurement.
2. Phase D automatic Canvas evidence.
3. Phase E assistant orchestration.
4. Phase F learning.
5. Phase G Gmail/document/calendar integrations.
6. Phase C effort/progress.
7. Phase B work priority using enriched evidence and usable-time schedules.
8. Phase H operational hardening.

This order intentionally finishes missing core intelligence features before final priority
calibration. A temporary priority implementation built before evidence, effort, and schedule data
would reproduce the current shallow ranking problem.

Each phase receives focused tests, compile validation, migration proof when applicable, one commit,
Azure backup before deployment, live health verification, and rollback notes. Do not wait until the
end to deploy multiple unverified schema or scheduler changes together.

## 13. Explicit Non-Goals

- no model fine-tuning before privacy-scrubbed evaluation data proves it useful;
- no multi-user/public launch work;
- no autonomous email or Canvas writes;
- no AI-created deadlines or direct AI reminder decisions;
- no hidden chain-of-thought display;
- no UI redesign during backend phases beyond exposing new verified fields;
- no inherited Odysseus full test suite unless quarantined legacy behavior changes.

## 14. Final Acceptance

Core backend is complete when DueSoon can:

1. rank immediate danger and work-to-start as separate explainable decisions;
2. cross-reference connected academic sources into validated evidence;
3. resolve or safely expose deadline conflicts;
4. estimate effort, compute start-by/slack, and learn from outcomes reversibly;
5. answer general questions while being materially stronger on school questions;
6. state exactly which missing app or permission blocks a better answer;
7. show a decision trace for evidence, assumptions, calculations, tools, and learning;
8. preserve checkpoint crossing, deduplication, immediate Canvas recheck, and ntfy reliability;
9. survive restart and restore without duplicate notification bursts; and
10. pass focused unit, integration, contract, end-to-end, migration, and production health checks.
