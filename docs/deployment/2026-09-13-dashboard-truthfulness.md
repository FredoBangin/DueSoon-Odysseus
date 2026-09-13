# Dashboard Truthfulness Release — 2026-09-13

## Scope and acceptance

This release corrects dashboard and assistant projections without changing urgency weights, reminder timing, source authority, persistence schema, or notification delivery behavior. It reuses the approved DueSoon composition and existing Odysseus UI primitives.

- Aggregate completion and workload answers count all published assignments rather than a ten-row display slice.
- Active assignments without a resolved operational deadline are visible and explicitly counted. An empty Urgent panel is not represented as proof that work is complete.
- Work priority exposes an additive planning state and explanation. Missing deadline or effort information is not presented as an unexplained MONITOR recommendation. The existing numeric score and band remain unchanged for compatibility.
- Recently completed work uses actual submission or grading timestamps within fourteen days, rather than assignment ingestion timestamps. Completed rows reuse the existing calendar strike-through treatment.
- The next known deadline excludes past overdue dates; overdue work remains in its own projection.
- Canvas freshness is based only on successful Canvas syncs, never a newer Google sync.
- Exact common school checks remain deterministic. Novel questions containing words such as "due" or "complete" are not silently hijacked into a canned answer.
- The Assistant route has a working shared composer, accepts arbitrary text, and prevents duplicate requests while a submission is pending.
- Provider configuration is reported as disabled, unconfigured, or configured but unverified. Configuration alone never proves provider reachability or quota.

## Verification

- Full DueSoon Python suite: 240 passed.
- Compile check: passed.
- Dependency-free JavaScript runtime fixture: passed. It exercises the real Home and Assistant view modules against a minimal DOM ownership model, including pending-submit deduplication and follow-up messages. It is not a substitute for visual browser acceptance.
- JavaScript modules use scoped `type: module` metadata so the runtime fixture does not depend on a removed experimental Node flag.
- CI includes DueSoon JavaScript syntax checks and the view runtime fixture.

## Production baseline before release

The freshly inspected Azure checkout was `74fd4ca`. DueSoon and ntfy were healthy, one live scheduler was enabled, and the latest Canvas sync completed. Successful daily notification delivery remained present in persisted history. No notification was sent during this inspection.

The model was disabled and no model API key was present in the running configuration. Module-linked Canvas page capture existed, but structured claims remained absent. Calendar busy blocks were absent at the inspection point. These findings are limitations, not proof that academic intelligence is fully operational.

## Remaining gates

1. Connect and verify a sustainable, owner-approved model provider before enabling model-backed extraction or broad assistant answers. Provider-side revocation of the previously exposed credential has not been proven.
2. Prove source-to-claim-to-admitted-evidence materialization and review representative deadline conflicts before changing urgency calibration.
3. Verify calendar busy-block coverage against a real work schedule and retain honest empty/disconnected states.
4. Complete authenticated browser visual acceptance and the remaining master-plan acceptance gates.

Production backup, deployment commit, and live verification must be recorded after deployment; this document does not claim a deployment that has not happened.
