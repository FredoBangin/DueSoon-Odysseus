# Discord academic updates

Status: optional mirror approved September 28, 2026; policy superseded by the
owner's grilled decisions on September 29, 2026. This document describes the
current policy. ntfy remains the primary private reminder provider.

## Approved behavior

- Sender: `Bob, From DueSoon`. Orange readable embeds with a title, paragraphs,
  headings, native timestamp, and exact local date/time footer. No numbered code
  logs and no duplicate embed author (the owner removed that field manually).
- Do not mirror checkpoint, adaptive, or daily ntfy reminders. Explicit transport
  tests may still use both providers when separately requested.
- Queue every new official Canvas course announcement, including nonurgent posts,
  and revised announcements. An initial historical import is not new professor
  activity. If a post changes while queued, summarize its latest version rather
  than sending obsolete wording. Every current queued post remains eligible;
  bounded batches do not discard the overflow.
- Also queue meaningful operational-deadline changes, conflicts, and missing
  timing for exams/projects. A major-title change qualifies regardless of size;
  other deadline moves qualify at six hours or more, or when a formerly missing
  date is established. This is notification selection, not an urgency score.
- No filler daily digest. Send pending facts at most once per 48 hours, measured
  from audited attempts that were sent, ambiguous, pending, or safely retrying.
  Up to five events fit a description of at most 3,900 rendered characters.
  Overflow stays pending for the next bundle. Restart does not reset cadence.
- Include what changed, exact dates, source, why it matters, next action, and any
  question requiring owner context. Never calculate a date from a bare weekday.
- Urgent new earlier deadlines or conflicts within 48 hours can use ntfy without
  waiting for Discord. Fresh Canvas submission checks are mandatory. Reuse a
  current-deadline checkpoint sent in the same evaluation rather than double-ping.
- Questions open the existing authenticated dashboard assistant. The user may
  reply naturally with any relevant detail. Store a private linked AcademicNote
  and response timestamp, not an automatic deadline confirmation. At most one
  unanswered follow-up is eligible after 48 hours, subject to global cadence.
  Answering stops that follow-up. New independent risk may create a new event.
- A webhook cannot receive Discord replies. No Discord bot, new scheduler,
  calendar provider, or AI-provider migration is part of this implementation.

## AI availability and honest fallback

The owner deferred model testing until they add an API key. Deterministic change
detection and verified alerts work independently. Announcement presentation is
currently a bounded plaintext source excerpt explicitly labeled **not AI analysis**,
with source publication time and a review link. This is not a claim that a model
has summarized or understood the full announcement. Verified AI summarization
and instruction interpretation remain pending provider setup and proof.

Linked replies pin the selected update into existing assistant retrieval. When
the provider is unavailable, the answer states that context was saved and AI
interpretation is unavailable. The answer shown to the owner is also the audited
answer. Learning never silently changes canonical deadlines or reminder timing.

## Privacy and safe delivery

Use a private Discord channel: its members and Discord can read the minimal course
context the owner explicitly approved. Announcement excerpts are limited to 320
characters, stripped of scripts/styles, and redact contact addresses, URLs, and
credential-like strings. Full private messages, documents, grades, tokens, and
webhook URLs are not published or included in diagnostics/model prompts. Student
content must not be printed in deployment logs or committed to Git.

The webhook is an environment-only secret. Only HTTPS `discord.com` webhook URLs
are accepted; redirects are disabled and `allowed_mentions.parse` is empty.
Webhook error details are sanitized. `wait=true` requires a confirmed message ID.

Before each live assignment-related update or retry, recheck submission in Canvas
and validate the current operational projection again. Completed, unpublished,
inactive, or obsolete facts are suppressed; unknown or failed checks cannot send.
Announcements alone are informational source updates, not assignment reminders.
No submission claim is inferred from announcement content.

Each bundle has a unique audit key, rendered body, provider outcome, and a
NotificationMirrorContext containing exact deadline versions, check observations,
expiry, attempt count, and next attempt time. Safe failures allow at most three
attempts within 48 hours, honor Retry-After and backoff, and never resend ntfy.
Timeouts, unconfirmed responses, 5xx errors, and interrupted pending sends remain
unknown and are never blindly replayed. Dry-run never contacts either provider.

## Persistence, activation, and rollback

The additive `academic_update_events` table stores versioned facts, immutable
source/assignment references, queued and follow-up delivery IDs, reply note IDs,
and lifecycle timestamps. Existing tables and records are not rebuilt or deleted.
SchedulerState retains activation and scan watermarks. Operational projection
baselines detect changes from admitted professor evidence as well as Canvas.
Announcement publication is compared with activation, not the last five-minute
scan; slower content syncs must not lose announcements posted between scans.

One existing scheduler synchronizes Canvas, evaluates ntfy reminders, and then
runs academic updates. A secondary failure cannot undo primary delivery. Startup
cancels unsent routine Discord retries from the superseded mirror policy, keeps
their history, and marks interrupted sends unknown. Old sent notices are not
replayed. First activation records current facts without a historical flood.

Default: `DUESOON_DISCORD_ENABLED=false`. Enable with the ignored server secret
after focused mock-provider, additive-schema, cadence, recheck, reply, and dry-run
proof. Before deployment, preserve a SQLite online backup and rollback image.
One owner-authorized, audited real-source preview may verify display and transport
without inventing a change or advancing the routine update cadence.

Rollback: disable Discord first and restart, then restore the previous app image
if required. Older images would otherwise resume their old mirror policy. Keep
the additive tables and audit rows; do not delete them or replay messages.

## Official protocol contracts

- [Execute Webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook)
- [Embed Object](https://docs.discord.com/developers/resources/message#embed-object)
