# ADR 0001: Azure VM and ntfy Runtime

**Status:** Accepted
**Date:** 2026-08-26

## Decision

Run the initial DueSoon production service on one Azure Linux VM using Docker Compose. Mount an attached Azure managed disk into the DueSoon container and store SQLite there. Run exactly one scheduler while SQLite is the persistence engine.

Use a private self-hosted ntfy service as the primary iPhone notification provider. Require HTTPS, bearer-token authentication, private topics, and ACLs. Configure ntfy's upstream base URL for iPhone APNs delivery. Keep notification content concise because delivery metadata may transit the upstream relay.

Twilio is an optional future adapter and is not required for the first release.

## Consequences

- Local Docker Desktop availability does not constrain production.
- SQLite must not be placed on Azure Files or another network file share.
- Horizontal application scaling is not allowed while the in-process scheduler and SQLite are used.
- Live delivery cannot be enabled until ntfy authentication, HTTPS, persistence, and the iPhone subscription are verified.
- Provider HTTP 429 and pre-delivery connection failures are retryable using the existing delivery
  intent. Every reminder retry still performs a fresh Canvas submission recheck first. Timeouts,
  other uncertain request failures, and HTTP 5xx responses remain `unknown` and are not retried
  automatically because duplicate iPhone pushes would be possible. Permanent HTTP 4xx responses
  remain failed and deduplicated.
