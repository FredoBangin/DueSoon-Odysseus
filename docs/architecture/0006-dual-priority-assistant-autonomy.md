# ADR 0006: Separate Work Priority and Bounded Assistant Autonomy

**Status:** Accepted
**Date:** 2026-08-28

## Context

`urgency-v2` correctly measures immediate deadline risk, but it is not a complete answer to
"what should I work on next?" Production data exposed this distinction: assignments more than
seven days away receive no time-pressure points, and similarly weighted assignments collapse
into the same LOW band even when a large project should be started before a smaller, nearer task.

DueSoon also needs an assistant that can answer general questions while being substantially
better at academic questions through connected evidence, tools, memory, and feedback. A scripted
intent list is not sufficient.

## Decision

DueSoon maintains two separate, explainable decisions:

1. **Urgency** is an absolute 0–100 measure of deadline danger. It continues to control reminder
   escalation and remains deterministic.
2. **Work priority** answers what should be started or continued now. It is based primarily on
   remaining slack: usable available time minus estimated effort minus a schedule buffer. Usable
   time excludes known sleep, classes, work, appointments, and other blocked periods from connected
   calendars or owner-approved schedule memory. It may also
   consider prerequisites, workload clusters, assignment value within its course, recent
   instructor warnings, and confirmed student behavior.

Estimated effort may be proposed by AI after cross-referencing assignment instructions, Canvas
modules, files, messages, professor email, points, assignment type, and historical outcomes.
Deterministic code validates the estimate and calculates slack and priority. Uncertain estimates
remain visible with provenance and confidence. They affect work priority only; they do not alter
deadlines, submission state, reminder checkpoints, or urgency.

The assistant is general-purpose and school-specialized:

- it may answer any safe question supported by its configured model;
- academic questions use structured retrieval across connected school sources;
- it identifies the exact missing application, connection, or permission when more context is
  required;
- connected school sources are read-only by default;
- external writes require a separately approved capability and user action; and
- model failure never disables deterministic Canvas reminders.

Low-risk learning may be applied automatically when it is fully audited and reversible. Initial
automatic categories are owner preferences, course-scoped assignment aliases, answer-format
preferences, and effort-estimation corrections. Deadline values, submission state, reminder
timing, professor identity, and source-authority changes require review and the existing validated
evidence path. Sending email, changing Canvas, deleting evidence, or exposing secrets is never an
automatic learning action.

DueSoon exposes a **decision trace**, not private model chain-of-thought. The trace includes sources
consulted, evidence references, assumptions, confidence, deterministic factor calculations,
tool/application activity, learned changes, and a concise explanation of why the answer was
selected over material alternatives.

## Consequences

- LOW urgency no longer means "ignore this work"; work priority can surface a large project early.
- Reminder behavior stays compatible with existing checkpoint, recheck, and deduplication rules.
- Work-priority records need versioned factors, effort provenance, confidence, and outcome feedback.
- Missing calendar/schedule context keeps usable capacity, start-by time, and exact slack unknown.
  A deterministic workload-density heuristic may still provide a low-confidence relative ordering,
  but DueSoon must not invent a fixed number of usable hours per day. Connected read-only calendar
  blocks, especially work shifts, can later supply usable windows.
- Capacity learning requires more than Canvas submission timestamps. Submission outcomes may trigger
  owner questions about time spent; progress history, confirmed effort, and calendar availability
  can then produce a reviewable, reversible capacity estimate after enough observations exist.
- Calendar planning stores privacy-minimized busy intervals and hashed event identifiers, not event
  titles or descriptions. A day without known blocks is not automatically treated as fully free.
- General answers can use the model without granting unrestricted tool, filesystem, secret, or
  network access.
- Automatic learning requires an append-only audit event and a reversible current-state projection.
