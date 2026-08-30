# ADR 0007: Bounded course-document extraction

## Status

Accepted on 2026-08-29.

## Decision

DueSoon may extract inert text from Canvas course files only when the file is PDF, DOCX, HTML,
or plain text and is within the configured byte limit. Downloads must use a same-origin Canvas URL,
must not follow redirects, and must stream into a bounded buffer. Signed, preview, and thumbnail
URLs are removed before source metadata is persisted.

PDF extraction is limited to 100 pages. DOCX extraction reads only the bounded
`word/document.xml` member and rejects encrypted or suspiciously compressed archives. Extracted
text is capped at 12,000 characters and stored with format, locator scheme, and truncation metadata.
Unchanged file revisions reuse the prior immutable extraction instead of downloading or consuming
model calls again.

Extracted text remains untrusted evidence data. It receives no tools, cannot issue instructions,
and enters the same schema-constrained claim validation, course-scoped assignment matching,
authority, recency, conflict, and review path as other Canvas evidence. Deterministic code retains
exclusive ownership of effective deadlines, operational deadlines, priority, and reminders.

## Consequences

- Course documents can support deadline and workload understanding without exposing signed URLs.
- Cross-origin Canvas CDN redirects are rejected by default. A future CDN adapter requires an
  explicit host policy and separate security review; silently weakening this boundary is forbidden.
- Image-only PDFs produce no usable text until a separately bounded OCR design is approved.
- Unsupported, oversized, malformed, redirected, and unavailable files remain visible as sanitized
  extraction status rather than causing canonical Canvas synchronization to fail.
