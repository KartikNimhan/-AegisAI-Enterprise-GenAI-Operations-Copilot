# 16. Input Bounds, History Window and Extraction Limits

> **Milestone numbering.** Uses the [Official Project Roadmap](../../../README.md#official-project-roadmap)
> (M1 LLM Gateway, M2 Conversational AI, M3 Document Intelligence, M8 GenAI UI + APIs).

## Status

Accepted — 2026-10-22. Implemented and verified offline (unit tests, in-memory probes). No database,
live provider or browser was involved.

## Context

An end-to-end review found places where one request could cause unbounded work or cost:

- Chat, RAG, agent and multi-agent endpoints accepted blank messages and (probed) 2,000,000-character
  messages, each of which would be sent to the model provider.
- Every turn replayed the **entire** stored conversation into the prompt, so long conversations grew
  in cost and latency and eventually failed on the provider's context limit.
- The 20 MB upload limit bounds the file, not what it expands to: a synthetic 428 KiB DOCX expanded to
  about 80 million characters in about 21 s; a PDF can declare any number of pages.
- A provider `Retry-After` of any size was slept on, holding the request open.
- An unhandled-exception 500 was the only response without `X-Request-ID`.

## Decisions

- **Request bounds** live in `app/core/limits.py` as code constants (a bound on what the API
  accepts is a contract, not a deployment knob), and are applied by shared annotated types in
  `app/api/schemas/common.py`: messages are stripped, non-empty and at most 32,000 characters;
  document-task id lists, analyst expressions and evidence are capped. Violations are ordinary 422s.
  The web composer mirrors the message cap (`maxLength`), and a test fails if the two drift.
- **History window** (`app/prompts/history.py`): the newest messages that fit
  `CHAT_HISTORY_MAX_MESSAGES` (40) and `CHAT_HISTORY_MAX_CHARS` (24,000). Messages are included whole
  (a large old one is dropped, never truncated), order is kept, and the window starts on a user turn.
  Older turns stay stored and visible; they are simply not replayed. Nothing is summarised.
- **Extraction limits** (`ExtractionLimits`): `DOCUMENT_MAX_UNCOMPRESSED_BYTES` (DOCX total expanded
  size, checked from the zip directory before any decompression, plus a 10,000-part cap),
  `DOCUMENT_MAX_PDF_PAGES`, `DOCUMENT_MAX_EXTRACTED_CHARS` (all formats). Exceeding one fails that
  document with a clear message; nothing is truncated silently.
- **Retry-After** above 20 s is not slept on: the error surfaces immediately and is recorded.
  The gateway also records any non-`LLMError` provider exception as error type `other` before
  re-raising.
- **500 responses** now carry `X-Request-ID`. `METRICS_TOKEN` with surrounding whitespace is rejected
  at startup (a trailing newline from a secret file would otherwise 401 every scrape silently).

### Added in the gap-remediation pass

- **Request bodies** larger than `MAX_REQUEST_BODY_BYTES` (16 MiB) are refused with 413 before
  parsing (`BodySizeLimitMiddleware`); multipart uploads are exempt and keep their own limit.
- **Streams** have a total deadline, `LLM_STREAM_TOTAL_TIMEOUT_SECONDS` (300 s). The per-request
  timeout only bounds waiting for data, so a stream that trickled forever was never cut off.
- **A2A responses** are read incrementally and refused above `A2A_MAX_RESPONSE_BYTES` (1 MiB); a
  declared or counted size over the cap, a malformed `Content-Length`, non-JSON, or a body of the
  wrong shape is a typed `A2AResponseError` / `A2AInvalidCardError`. A whole exchange has a
  deadline, `A2A_TOTAL_TIMEOUT_SECONDS` (30 s), on top of the per-phase HTTP timeout. Error text
  from a remote agent is never forwarded: clients get a fixed message per failure class, details go
  to logs (exception type only for connection errors, which can carry addresses).
- **One failing agent** no longer fails a multi-agent request: anything unexpected an adapter raises
  becomes that agent's failed result (not retried), and its siblings finish.
- **Malformed tool arguments** from the model (not JSON, or not an object) are answered with a
  validation error as the tool result; the run continues.
- **`EMBEDDING_DIMENSION`** must equal the `chunk_embeddings` column (384); `create_app` refuses to
  start otherwise. Changing the dimension needs a new migration, never just a setting.
- **The stdio MCP server** has no signed-in caller, so it refuses to start unless told whose data
  to serve: `MCP_STDIO_USER_ID` + `MCP_STDIO_ORGANIZATION_ID` (preferred: the same ownership rules
  as the API) or an explicit `MCP_STDIO_ALLOW_UNRESTRICTED=true` (all organizations).
- **Document context** neutralizes text shaped like our markers (`[SOURCE n]`, `[S3]`) inside chunks
  and file names, so a document cannot forge a source boundary or plant a citation the sanitizer
  would accept. This is a mitigation, not a guarantee against prompt injection (see ADR 007).
- **Service factories** (chat, RAG, agent) take settings through dependency injection like the rest
  of the application.
- **Concurrency** (implemented, not integration-verified, PostgreSQL only): memory writes lock the
  owner's `users` row (`SELECT ... FOR UPDATE`) so the per-user cap holds under concurrent writes;
  uploads of identical bytes by one user serialize on a transaction-scoped advisory lock keyed by
  user and checksum, so a duplicate-upload race stores one document. Other databases skip both.

## Consequences

- Clients that sent >32,000-character messages now get 422.
- Declared zip sizes are a ceiling, so the DOCX check is safe against a lying directory.
- A DOCX inside the limits can still be slow to parse; the limits are ceilings, not a sandbox.

## Not done / not verified

- The extraction limits have not been exercised against real-world large documents; defaults are
  generous starting points.
- The dimension check compares configuration with the schema constant. It does not read the live
  database's column definition.
- A unique index on `(owner, checksum)` is the real fix for duplicate uploads, but existing data may
  already hold duplicates, so it needs an operator to inspect and de-duplicate first. Follow-up:
  `SELECT owner_user_id, checksum, count(*) FROM documents GROUP BY 1, 2 HAVING count(*) > 1;`,
  resolve the rows, then add `UNIQUE (owner_user_id, checksum)` in a new migration. Until then the
  advisory lock above narrows the race but the database does not forbid duplicates.
- A hard cap on memories per user would also be a database-level guarantee (a counter column or a
  trigger). The row lock gives the same effect only while every writer goes through the service.
- The advisory lock and the row lock have not run against PostgreSQL in this work.
