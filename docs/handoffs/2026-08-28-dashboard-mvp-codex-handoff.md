# DueSoon Dashboard MVP — Codex Handoff and Memory Transfer

## Read First

This file transfers the current working memory to another Codex agent with access to the same machine. Continue from the existing repository; do not restart or re-fork.

Read these files completely, in order:

1. `AGENTS.md`
2. `DUESOON_CODEX_CONTEXT.md` — foundational product specification and learning base, not optional notes
3. `docs/superpowers/specs/2026-08-27-duesoon-dashboard-assistant-design.md`
4. `docs/superpowers/plans/2026-08-27-duesoon-dashboard-mvp.md`
5. this handoff

Repository: `D:\odd`

Git remotes:

- `origin`: `https://github.com/FredoBangin/DueSoon-Odysseus.git`
- `upstream`: `https://github.com/odysseus-dev/odysseus.git`

The user wants all new project files kept under `D:\odd`. Work inline and conserve usage. Do not run the inherited Odysseus test suite; only run `tests/duesoon`.

## User Priorities and Decisions

- Deliver a working web MVP before model AI, Gmail, Google Calendar, PWA/native, or optional retained tools.
- Keep the useful Odysseus feel and tabs, but do not activate its legacy backend or dangerous generic tools.
- Main tabs: Home, Assistant, Calendar, Email, Notifications, Review, Settings.
- Notes, Memory, and Documents remain visible as retained/deferred capabilities.
- Home shows urgent/upcoming/missing/completed work, freshness, and assistant entry.
- Calendar must feel familiar to Canvas and provide month/week/agenda, course colors, statuses, and read-only Canvas links.
- MVP assistant is deterministic and must answer “Any updates?”, “What is due next?”, “What am I missing?”, and “Did I submit everything?” without an AI provider.
- Later model AI uses the existing OpenAI-compatible key, configurable primary/fallback models, bounded costs, evidence links, and no authority over deterministic reminders.
- Later learning asks what was wrong and creates visible, reversible proposals. It cannot silently alter canonical deadlines, submissions, or reminder timing.
- School email is Gmail; later integration is read-only OAuth and minimal caching.
- ntfy remains the current notification provider for iPhone. Twilio is deferred.
- Azure is the runtime target; local Docker limitations do not constrain the design.
- Single-owner web login is separate from ntfy credentials and API-token automation.
- The user explicitly waived the final Codex Security scan on 2026-08-28 because account usage was low. Keep security controls and focused tests, but do not spend usage invoking Codex Security unless the user reauthorizes it.

## Non-Negotiable Runtime Invariants

- Never send a reminder without immediate Canvas submission recheck.
- Preserve checkpoint crossing at 24h/12h/6h/1h/15m.
- Preserve database deduplication, dry-run behavior, and audit history.
- Use exactly one scheduler with SQLite.
- Keep SQLite on the Azure managed disk at `/mnt/duesoon/app`.
- Do not expose or commit secrets/student raw payloads.
- Preserve private ntfy ACLs and all iPhone topic/subscription routes.
- Browser session credentials must never cross into the existing API-token boundary.
- Dashboard decisions use the explicit Canvas-baseline Effective Assignment projection, naming Canvas as the evidence source.

## Known Production State Before This MVP

- Previously deployed code commit: `2b8173f` (`feat: run Canvas reminders on schedule`).
- Azure host: `azureuser@duesoon-revxn-prod.northcentralus.cloudapp.azure.com`
- Azure repo: `/opt/duesoon`
- SSH private key: `D:\odd\.tools\ssh\duesoon-prod-revxn`
- SSH known-hosts file: `D:\odd\.tools\ssh\known_hosts-revxn`
- Compose environment: `/etc/duesoon/compose.env`
- Runtime secrets: `/etc/duesoon/duesoon.env`
- Owner credentials: `/etc/duesoon/owner-credentials.env`
- Persistent database: `/mnt/duesoon/app/duesoon.db`
- Scheduler interval: 300 seconds; exactly one worker.
- Last known live Canvas sync: 3 courses and 193 assignments/submissions.
- One controlled real checkpoint notification had reached ntfy/iPhone.
- Health was 200 with zero restart loops.
- Do not print or commit any file under `.tools`, `/etc/duesoon`, or the database.

## Completed Documentation Commits

- `2a7ebe9` — dashboard/assistant architecture and source-of-truth extension.
- `1418b15` — full 12-task dashboard MVP implementation plan.

These commits were local before this handoff checkpoint. Confirm whether the final checkpoint is on `origin/main` before deploying.

## MVP Code Implemented in the Current Working Tree

Backend/security:

- Added web settings and production validation in `src/duesoon/config/settings.py`.
- Added `WebSession` and `LoginAttempt` persistence tables.
- Added versioned stdlib scrypt password hashing with stdin-only generator.
- Added persistent login throttling, random server-side sessions, hashed session tokens, CSRF tokens, revocation, and expiry.
- Separated `require_api_token`, `require_browser_session`, and `require_csrf` dependencies.
- Added login/session/logout and protected app routes.
- Added no-store and no-sniff response handling.

Academic/dashboard:

- Added Canvas-baseline `EffectiveAssignment` projection.
- Added urgency-v1 0–100 scoring with time/value/workload/change/submission factors and LOW/MEDIUM/HIGH/CRITICAL levels.
- Added real persisted briefing groups, freshness, and reminder counts.
- Added read-only calendar projection with stable course colors and timezone display.
- Added deterministic assistant and evidence links.
- Added notification history plus safe Review and Settings foundations.

Frontend:

- Added focused local HTML/CSS/ES-module application under `src/duesoon/web/static`.
- Added Odysseus-derived dark navigation shell and responsive mobile bottom nav.
- Added Home, Assistant, Calendar, Notifications, Review, Settings, Email, Notes, Memory, and Documents views.
- No service worker, local/session storage, API token, remote script, or active inherited Odysseus runtime is used.

Operations:

- Caddy now routes only `/`, `/login`, `/app*`, `/assets/*`, `/api/*`, health/docs paths to DueSoon; all other paths continue to ntfy.
- Added CSP, Permissions Policy, and frame denial.
- Added `deploy/azure/configure-owner-login.sh` with prompt or `--generate` mode.
- Fresh provisioning now creates separate ntfy and web passwords and stores only the web hash in runtime environment.

## Verification Already Completed

Immediately before this handoff:

```text
83 passed in 20.27s
python -m compileall -q src/duesoon: passed
git diff --check: passed (CRLF warnings only)
```

New test file: `tests/duesoon/test_dashboard_mvp.py`.

It covers password hashing, login/session/CSRF/logout, browser authorization, real Canvas briefing, Effective Assignment date exposure, calendar read-only projection, deterministic assistant, approved navigation, and absence of browser secret storage/service workers.

## Important Remaining Work

Do these in order:

1. Inspect `git status` and `git diff` in `D:\odd`.
2. Run the focused suite again with the local interpreter:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/duesoon -q
   .\.venv\Scripts\python.exe -m compileall -q src/duesoon
   git diff --check
   ```

3. Run JavaScript syntax checks if Node is available:

   ```powershell
   node --check src/duesoon/web/static/js/app.js
   node --check src/duesoon/web/static/js/api.js
   Get-ChildItem src/duesoon/web/static/js/views/*.js | ForEach-Object { node --check $_.FullName }
   ```

4. Inspect and test `deploy/azure/provision-runtime.sh` and `configure-owner-login.sh` on Linux. The current Windows host may not have a usable Bash/WSL environment.
5. Update `deploy/azure/verify-runtime.sh` to test web login and authenticated briefing without printing secrets. This was planned but not implemented.
6. Consider adding focused assertions to `tests/duesoon/test_runtime_manifest.py` for the new Caddy paths/headers and owner configuration script.
7. Commit the MVP checkpoint and push `main`.
8. Before Azure deployment, back up `/mnt/duesoon/app/duesoon.db` to a timestamped file on the managed disk.
9. On Azure, pull the pushed commit and run:

   ```bash
   sudo /opt/duesoon/deploy/azure/configure-owner-login.sh duesoon-owner --generate
   cd /opt/duesoon
   sudo docker compose --env-file /etc/duesoon/compose.env -f deploy/azure/docker-compose.production.yml config --quiet
   sudo docker compose --env-file /etc/duesoon/compose.env -f deploy/azure/docker-compose.production.yml up -d --build
   ```

10. Copy `/etc/duesoon/owner-credentials.env` securely to an ignored local file under `D:\odd\.tools` so the user can access the web username/password. Never display the secrets in chat or logs.
11. Verify production health, login, briefing, calendar, scheduler interval, live Canvas sync, ntfy ACL, and zero restart loops.
12. Do not send another controlled ntfy message unless the user authorizes it; existing live reminder delivery should remain untouched.

## Review Points for the Next Agent

- `BriefingService` currently treats a missing/latest unsuccessful `SyncRun` as stale, which is safe. Confirm the actual successful status string written by `CanvasSyncService` before changing freshness behavior.
- Windows may not have the IANA tzdata wheel. `BriefingService` falls back to the Windows local timezone only when `ZoneInfo` is unavailable; Azure Linux should use its system IANA database. Verify `America/New_York` inside the production container.
- `create_schema()` adds the two new auth tables through SQLAlchemy `create_all`; no existing table is altered.
- `configure-owner-login.sh --generate` stores the generated web password only in the root-readable owner credentials file. Ensure mode 0600 remains intact.
- `provision-runtime.sh` writes runtime environment twice during fresh provisioning; web settings must remain in the second/final heredoc. This handoff patch added them—verify before commit.
- The web UI is a dependency-free MVP. Browser visual verification is still required at desktop and iPhone-sized widths.
- The original plan’s Codex Security steps are superseded only by the user’s explicit waiver. Do not claim a Codex Security scan was run.

## Recommended Immediate Prompt for the Next Codex

> Work from `D:\odd`. Read `AGENTS.md`, `DUESOON_CODEX_CONTEXT.md`, the dashboard design, implementation plan, and `docs/handoffs/2026-08-28-dashboard-mvp-codex-handoff.md` completely. Continue the existing dashboard MVP working tree; do not restart. Re-run the 83 focused DueSoon tests, verify the shell/operations changes, commit and push the checkpoint, deploy it to the existing Azure host, securely copy web credentials into an ignored `.tools` file for the owner, and verify login/dashboard/Canvas scheduler/ntfy continuity. The owner waived Codex Security scans due to usage constraints, so keep security tests but do not invoke security scanning unless reauthorized.
