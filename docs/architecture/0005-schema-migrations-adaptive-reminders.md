# ADR 0005: Forward-Only SQLite Migrations and Adaptive Reminder Audit

## Decision

DueSoon applies numbered, idempotent SQLite migrations after creating missing tables. Migration 1 adds `reminder_kind` and `interval_key` to reminder events and a unique adaptive-interval index.

Standard reminders retain the five mandatory checkpoints. When a verified deadline moves at least six hours earlier, DueSoon may label the single safe catch-up send as adaptive only when it is more than thirty minutes from the next standard checkpoint. Adaptive delivery uses its own deduplication key, still performs the immediate Canvas submission recheck, and records the exact checkpoint interval.

## Safety

Production data is backed up with SQLite's backup API before deployment. Migrations are additive and preserve prior event rows as `standard`. Rolling application code back does not delete the new columns or alter existing reminder outcomes.
