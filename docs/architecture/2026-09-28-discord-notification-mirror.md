# Optional Discord notification mirror

Status: approved by the owner on 2026-09-28.

## Scope and privacy

Private ntfy remains the primary reminder provider. An explicitly configured Discord
incoming webhook mirrors newly successful ntfy deliveries and controlled test
notifications. It does not replay older notices when first enabled. The embed uses
an orange accent, a numbered monospaced log body, an exact local timestamp, and
Discord's native timestamp display. Existing deadline rendering is preserved.

Discord and members of the webhook's channel can read the same minimal academic
titles, course names, and deadline text sent to ntfy. Use a private channel. The
webhook URL is a credential: keep it in the ignored environment file, never in
source, browser APIs, images, logs, or model prompts. Only HTTPS discord.com webhook
URLs are accepted, redirects are disabled, and allowed mentions are empty. Raw
professor messages, grades, documents, or secrets are not added to the payload.

## Safety and persistence

Each Discord message has its own NotificationDelivery row and a unique key derived
from the primary delivery ID. The additive notification_mirror_contexts table
stores assignment IDs, exact operational-deadline versions, expiry, attempt count,
next attempt time, and submission-recheck observations. Existing ntfy delivery IDs,
deduplication keys, reminder events, and history remain unchanged.

Every live academic mirror attempt rechecks each included assignment in Canvas.
Submitted or graded work suppresses the entire mirror, rather than sending a stale
saved digest. Unknown or failed rechecks cannot send. A changed, removed, expired,
or unpublished operational deadline suppresses the mirror. Checkpoint mirrors
expire at their operational deadline; daily mirrors expire at local midnight.

Transient rejections (429) or connection failures before delivery allow at most
three attempts, honoring Retry-After and bounded exponential backoff. Retries run
inside the existing single scheduler after Canvas synchronization. Secondary
failure never blocks primary reminder evaluation. Timeouts, unconfirmed success,
5xx responses, and interrupted pending sends are ambiguous: retain an unknown
outcome and never blindly resend. The wait=true webhook parameter requests a
confirmed Discord message ID. Dry-run records the secondary intent but never calls
Discord. Notification history identifies each provider and outcome independently.

## Rollout and rollback

The default is DUESOON_DISCORD_ENABLED=false. Configure the secret only on the server
and enable it after mock-provider tests, schema-preservation tests, and one
controlled live embed verification. The environment secret must be excluded from
Git and Docker build context. The new table is created through existing schema
initialization; no old table or row is rebuilt or deleted.

Rollback is to disable Discord and restart, or restore the previous app image.
The previous version ignores the additive context table. Keep Discord audit rows
and context during rollback; do not drop them or replay their messages.

## Official contracts

- [Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook)
- [Embed Object](https://docs.discord.com/developers/resources/message#embed-object)
