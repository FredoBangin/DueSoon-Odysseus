# DueSoon Production Baseline — 2026-09-01

**Status:** Phase 0 audit snapshot
**Local and origin commit:** `f7ee36a`
**Azure checkout commit:** `308604c`
**Environment:** Single Azure Linux VM, Docker Compose, SQLite on attached ext4 managed disk

This record contains only privacy-safe operational facts. It contains no credentials, academic content, topic names, email addresses, model prompts, or provider keys.

## Runtime State

- Production was healthy and serving HTTPS during the audit.
- Exactly one DueSoon container, one ntfy container, and one Caddy container were running.
- DueSoon and ntfy reported healthy; all three containers had zero restarts.
- Scheduler was enabled with one worker and live delivery enabled.
- Scheduler watermark lag was approximately one interval at the audit point.
- Latest Canvas sync completed successfully on 2026-09-01.
- SQLite was stored at `/mnt/duesoon/app/duesoon.db` on the attached ext4 managed disk.
- The managed disk had ample free capacity.
- Private ntfy delivery was configured. Persisted delivery history contained successful deliveries, including a recent daily briefing.
- Gmail and Google Calendar were configured and their auxiliary sync completed. Gmail source capture was active. Calendar stored no active busy blocks in the queried window; this is not yet proof of a broken OAuth connection.
- Model configuration was enabled and structurally configured. No provider request was made during the first audit, so configuration did not prove model reachability or available quota.

## Version Drift

Azure was one commit behind local/origin. The missing commit, `f7ee36a`, is the focused UI overflow fix. Production must not be described as running the current branch until a verified successor is deployed and its server/browser asset version is confirmed.

## Academic Intelligence Coverage

The critical production finding was not a UI-only defect:

- 3,560 immutable source records were captured.
- 194 published assignments existed; 178 were active.
- 166 assignments lacked `operational_due_at`.
- All 178 active assignments projected LOW urgency.
- No structured claims, admitted assignment-evidence links, or persisted resolved deadline evidence existed.

This explains the empty Urgent panel and weak priority output. Source capture is working, but the source-to-claim-to-evidence pipeline has not materialized production evidence. Provider failure/backoff and pipeline throughput are the leading mechanisms and require direct proof before changing scoring.

## Notification State

- The latest persisted notification was a successful daily briefing.
- Historical delivery rows included 13 sent and 1 failed result.
- No notification was sent during this audit.
- A controlled live notification remains owner-authorized-only.

## GitHub and Local Verification

- Current `origin/main` GitHub Actions were green at the audit point: 18 successful checks and 3 expected skips.
- Python tests, compile, JavaScript syntax, amd64/arm64 image builds, CodeQL, secret scan, workflow security, dependency audit, and container scans passed remotely.
- Local compile and JavaScript syntax passed.
- Production Compose validation passed locally when supplied non-secret validation placeholders and the repository example environment.
- Local test environment initially lacked declared `pypdf`; installing pinned repository dependencies corrected collection.
- The focused suite exposed an unsafe timezone fallback: if IANA timezone data was absent, an 8:00 AM local daily briefing could be evaluated as 8:00 AM UTC. The fix adds pinned `tzdata`, rejects unavailable configured zones, and suppresses a digest rather than guessing UTC.

## Immediate Release Order

1. Prove why production evidence extraction produces zero claims.
2. Disable and revoke the exposed/exhausted OpenAI credential before any provider funding.
3. Complete the focused test suite with the timezone fix.
4. Commit and push the master plan, baseline record, and verified timezone fix.
5. Back up SQLite, deploy the verified successor, and confirm commit/static asset version.
6. Recheck Canvas, scheduler, ntfy, model, Gmail, calendar, and evidence coverage without sending a notification.
