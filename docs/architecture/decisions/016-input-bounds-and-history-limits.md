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

## Consequences

- Clients that sent >32,000-character messages now get 422.
- Declared zip sizes are a ceiling, so the DOCX check is safe against a lying directory.
- A DOCX inside the limits can still be slow to parse; the limits are ceilings, not a sandbox.

## Not done / not verified

- The extraction limits have not been exercised against real-world large documents; defaults are
  generous starting points.
- Embedding-dimension agreement is checked by tests and migrations, not at startup against a live
  database.
