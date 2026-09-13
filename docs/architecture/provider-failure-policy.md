# Provider Failure Policy

Status: accepted implementation checkpoint, 2026-09-13.

## Decision

Keep the existing OpenAI-compatible adapter behind a small `ModelProvider` protocol shared by assistant answers and structured extraction. Do not add another provider account or framework merely to install failure protection.

The production application shares one provider instance between workflows. An in-process lock serializes its bounded request chains so simultaneous extraction and assistant calls cannot independently repeat a just-failed chain. Each configured fallback model appears at most once, and the existing per-request call budget remains authoritative. Serialization can delay an interactive answer behind one bounded extraction request; this is accepted for the current single-owner, single-worker deployment, not a scaling design.

When every allowed transient fallback fails, the circuit suppresses network requests for at least thirty seconds. HTTP Retry-After delta seconds and dates are honored within a thirty-second to one-hour policy bound. Explicit account quota exhaustion stops the chain immediately and pauses it for at least fifteen minutes. Authentication or other non-transient request rejection stops fallback and pauses requests for five minutes. Invalid structured output pauses requests for thirty seconds.

Cooldown is not a sleep: requests return a safe deterministic fallback immediately. Assistant and extraction share the circuit. Effective endpoint, credential fingerprint, or model-chain changes reset stale health so replacement credentials can recover without waiting for the old configuration's cooldown. The credential fingerprint is process-private and never appears in API output or persistence.

## Truthful health

Health exposes only a state, an allowlisted reason, and retry delay. States are disabled, unconfigured, unverified, cooldown, or healthy. Health reads never wait behind a provider network request; an in-flight request is reported as unverified with `request_in_progress`. Healthy means a structured provider request succeeded in this process; it does not certify account balance, remaining quota, citation quality, or extracted claim correctness. Settings display this distinction using existing UI components.

## Preservation and limitations

- No urgency weights, reminder checkpoints, Canvas pre-send checks, canonical deadlines, submission status, database schema, or notification provider behavior changes.
- Response bodies, prompts, credential values, and account identifiers never enter public health or error messages.
- Cooldown state is process-local and resets on restart. Durable cross-restart quota accounting, per-workflow aggregate budgets, provider-specific capabilities, and real provider evaluation remain unfinished master-plan work.
- Unknown quota responses are treated as bounded transient failures, not guessed account balances.
- A new live provider still requires owner-approved credentials and privacy terms. Existing subscriptions are not assumed to include API entitlement.

## Proof

Focused tests cover explicit quota exhaustion, duplicate fallback removal, Retry-After dates and bounds, timeout and rejection safety, credential replacement, invalid output, concurrent workflow failure sharing, sanitized settings health, and frontend health copy. Full DueSoon tests remain the release gate.
