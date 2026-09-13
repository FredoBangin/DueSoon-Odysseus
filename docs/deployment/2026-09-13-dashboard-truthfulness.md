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

No model API key was present in the running configuration. The authenticated projection reports the effective provider as unconfigured; persisted non-secret settings can override the environment enable flag, so an environment-only disabled flag must not be described as the complete effective state. Module-linked Canvas page capture existed, but structured claims remained absent. Calendar busy blocks were absent at the inspection point. These findings are limitations, not proof that academic intelligence is fully operational.

## Remaining gates

1. Connect and verify a sustainable, owner-approved model provider before enabling model-backed extraction or broad assistant answers. Provider-side revocation of the previously exposed credential has not been proven.
2. Prove source-to-claim-to-admitted-evidence materialization and review representative deadline conflicts before changing urgency calibration.
3. Verify calendar busy-block coverage against a real work schedule and retain honest empty/disconnected states.
4. Complete authenticated browser visual acceptance and the remaining master-plan acceptance gates.

## Completed deployment and live verification

- Deployed application commit: `71cc454` on 2026-09-13. Only the DueSoon container was recreated; ntfy and Caddy remained running.
- Pre-release SQLite backup: `pre-71cc454-20260913173228.db`, 150,487,040 bytes, integrity check `ok`, owner-only permissions.
- Application image manifest: `sha256:5d5c8c2b65168a9987a25687fec1ce1cfb96ca87c122b2267bc628d2c14dde20`.
- DueSoon and ntfy containers reported healthy. Web login and authenticated briefing returned HTTP 200.
- Fresh Canvas sync completed at 2026-09-13 17:33:09 UTC. Scheduler watermark lag was 100 seconds, or 0.33 configured intervals, at the final check.
- The live briefing counted 194 published assignments: 174 active, 20 completed, 20 dated active, and 154 undated active. Zero urgent items was accompanied by explicit missing-evidence information.
- There were zero admitted deadline-evidence assignments and zero structured claims. This release does not claim to have solved evidence extraction.
- Persisted delivery history remained 26 sent and 1 failed. Anonymous ntfy access returned HTTP 403. No controlled notification was sent.
- Served Home JavaScript contained the new missing-deadline projection. Its SHA-256 was `ee62185bfbbdea008d9334cc3575485754a6df50efb1069285432d622b0a7767`.
- The live login page was visually inspected: approved split-card composition and particle background were present. Authenticated dashboard visual acceptance still requires an active browser login; API and runtime-fixture checks are not claimed as visual proof.
- All eight GitHub workflow runs for `71cc454` completed successfully, including CI, Docker publish, dependency review, CodeQL, secret scan, workflow security, and both container scan workflows.

## Provider safeguard successor

The successor adds the shared provider protocol, failure cooldown, sanitized Settings health, quota-exhaustion suppression, bounded Retry-After handling, and duplicate fallback removal described in `docs/architecture/provider-failure-policy.md`. Full DueSoon tests passed again: 253 passed in 89.18 seconds. The frontend runtime fixture, JavaScript syntax, compile, and diff checks passed. No model request or notification was sent during these gates.

Pre-successor backup: `pre-provider-guard-20260913174356.db`, 150,589,440 bytes, integrity `ok`, owner-only permissions. The successor must still be verified on Azure before it is described as deployed.
