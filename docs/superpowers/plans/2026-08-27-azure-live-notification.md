# Azure Live Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing DueSoon Canvas prototype to one Azure Linux VM and deliver one authenticated, audited ntfy notification to the owner's iPhone.

**Architecture:** Keep the accepted single-VM topology: DueSoon, private ntfy, and Caddy run in Docker Compose; SQLite and ntfy state live on an attached managed disk. The API exposes one token-guarded test-delivery route. It records an idempotency key before publishing and never blindly retries an ambiguous result.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, httpx, Docker Compose, Caddy, ntfy v2.27.0, Azure Linux VM, Azure managed disk.

**Spec:** `DUESOON_CODEX_CONTEXT.md` and `docs/architecture/0001-azure-ntfy-runtime.md`

## Global Constraints

- Keep Twilio disabled; private self-hosted ntfy is the active provider.
- Production notification traffic requires HTTPS and bearer-token authentication.
- SQLite must use one scheduler worker and an Azure managed disk, never Azure Files.
- Do not commit API tokens, Canvas credentials, ntfy credentials, topics, hostnames, or student data.
- Dry-run must render and audit without contacting ntfy.

---

### Task 1: Authenticated and Audited Test Delivery

**Files:**
- Create: `src/duesoon/notifications/ntfy.py`
- Create: `src/duesoon/notifications/service.py`
- Modify: `src/duesoon/persistence/models.py`
- Modify: `src/duesoon/api/schemas.py`
- Modify: `src/duesoon/api/app.py`
- Test: `tests/duesoon/test_ntfy.py`
- Test: `tests/duesoon/test_notification_api.py`

**Interfaces:**
- Consumes: validated `DueSoonSettings`, SQLAlchemy session factory, and ntfy's JSON publish API.
- Produces: `NtfyPublisher.publish(...)`, `NotificationService.send_test(...)`, and `POST /api/v1/notifications/test`.

- [ ] Write a failing transport test proving JSON publishing uses the private topic and bearer token without leaking either value in errors.
- [ ] Run `python -m pytest tests/duesoon/test_ntfy.py -q` and confirm the missing module/interface failure.
- [ ] Implement the minimal ntfy publisher and rerun the test to green.
- [ ] Write failing API tests for token protection, dry-run behavior, persisted outcomes, and duplicate idempotency keys.
- [ ] Run `python -m pytest tests/duesoon/test_notification_api.py -q` and confirm the missing route/model failure.
- [ ] Add the delivery model/service/API, then rerun both notification test files and the full focused suite.

### Task 2: Production Azure Runtime

**Files:**
- Create: `deploy/azure/Caddyfile`
- Create: `deploy/azure/docker-compose.production.yml`
- Create: `deploy/azure/cloud-init.yml`
- Create: `docs/deployment/AZURE.md`
- Modify: `.env.example`
- Modify: `tests/duesoon/test_runtime_manifest.py`

**Interfaces:**
- Consumes: one Azure VM FQDN, a managed disk at LUN 0, and runtime secrets supplied outside Git.
- Produces: HTTPS routing, persistent paths, Docker installation/bootstrap, and repeatable operator commands.

- [ ] Add failing manifest tests for Caddy-only public ports, a one-worker DueSoon process, deny-all ntfy access, APNs upstream configuration, and managed-disk host mounts.
- [ ] Run the manifest tests and confirm they fail because production assets do not exist.
- [ ] Add the smallest production Compose, Caddy, and cloud-init assets that satisfy the checks.
- [ ] Validate the rendered Compose configuration and document secret/bootstrap steps without real values.

### Task 3: Deploy and Prove Delivery

**Files:**
- Modify only deployment documentation if the live run exposes a repeatable operational gap.

**Interfaces:**
- Consumes: the signed-in Azure subscription and the user's ntfy iPhone subscription.
- Produces: a healthy public HTTPS endpoint and one recorded provider message ID.

- [ ] Audit subscriptions/resource groups/VMs before creating resources.
- [ ] Create or reuse one scoped resource group, VM, public DNS label, NSG rules for 22/80/443, and attached managed disk.
- [ ] deploy the committed repository and root-owned production environment file without printing secrets.
- [ ] Create the ntfy user/token and topic ACL, then configure DueSoon with the publisher token.
- [ ] Verify HTTPS health, deny-all anonymous access, authenticated publish, database persistence, and container health.
- [ ] Call the guarded test-notification route once with a unique idempotency key and confirm its audit record/provider message ID.
- [ ] Run the complete focused test suite, inspect the final diff for secrets, commit, and push.
