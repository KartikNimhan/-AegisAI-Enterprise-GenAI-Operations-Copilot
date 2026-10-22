# 15. Agent Memory, RAG Filters/Citation Validation, and Streaming UI

> **Milestone numbering.** This document uses the [Official Project Roadmap](../../../README.md#official-project-roadmap)
> (M5 Production RAG, M6 Agentic AI, M8 GenAI UI + APIs).

## Status

Accepted — 2026-10-22. Implemented and verified offline (unit tests, SQLite-executed repository
tests, rendered migration SQL, vitest). **Migration 0008 has not been applied to any database and the
database-backed tests have not been run.**

## Context

Three roadmap items were still open: M5 had `document_id` as its only metadata filter and nothing
checked the `[S1]` citations a model wrote; M6 had no memory beyond replaying conversation history
(`app/memory/` was empty); M8's React Copilot did not use the existing SSE endpoints.

## Decisions

### M5: filters and citation validation

- `RetrievalFilters` (document id, document types, exact original file name, created-at range) is
  an allowlist over real `Document` columns, validated by the request schema (known enum values,
  length limits, timezone-aware dates, ordered range) and applied in `RetrievalRepository` as bound
  parameters **after** the access scope, before `LIMIT`. Filters can only narrow the scope. The
  top-K ceiling and context budget are unchanged. Not a generic filter language (ADR 007).
- Citations: `app.rag.citations`. Any `[S<n>]` / `[S1, S2]` marker whose id is not a retrieved
  source id is removed; valid ids in the same marker stay. The streaming sanitizer holds text from
  `[` only while it can still be a citation (bounded), so a marker split across chunks is checked
  too; what the client sees is what is stored. Responses report `invalid_citations`
  (non-streaming) and which sources the answer `cited`. Limitation: the stream cannot take back a
  space it already sent, so it may leave one before punctuation where the non-streaming path
  tidies it. Validation proves the id exists, not that the cited source supports the claim.

### M6: agent memory

- Table `agent_memories` (migration 0008, additive): owner + organization with the same composite
  foreign key as conversations/documents (`RESTRICT`), unique `(owner, content_hash)` so re-saving
  refreshes instead of duplicating, mandatory `expires_at`, kind (`fact`/`preference`), source
  (`agent`/`user`).
- **Ownership:** `AccessScope.memory_filter` (owner **and** organization); the repository cannot be
  told an owner. Not shared with the organization, not readable by administrators. Another user's
  memory id is a 404.
- **Lifecycle:** created by the agent's `save_memory` tool or by the user (`POST /memories`); edited
  and deleted only by the user (no agent tool deletes or edits); expires after
  `AGENT_MEMORY_TTL_DAYS`; expired rows are purged on the owner's next write; re-saving extends life.
- **Bounds:** item length, notes per user (a full memory refuses new notes, never evicts silently),
  writes per run (a per-request budget), notes and characters per prompt. Retrieval ranks the most
  recent notes by word overlap with the question (no embeddings: no second vector space to keep in
  step; a deliberate simplification).
- **Trust:** a note can be written while the agent reads untrusted text, so notes reach the model
  as a labelled system block saying they are data, not instructions; text is collapsed to one line
  and stripped of control/hidden characters; the write cap, the user-visible list and a one-call
  "forget everything" limit and undo a poisoning attempt. This reduces, not eliminates, memory
  poisoning risk.
- **Failure:** recall never fails a run (`recall_safely`, in a savepoint); writes run in a savepoint,
  so a database error becomes a tool failure the model sees, not a poisoned transaction.
- Audit events `memory.saved|updated|deleted|cleared` carry ids and counts, never note text.

### M8: streaming UI

- The Copilot reads `POST /api/v1/rag/chat/stream` with `fetch` + `ReadableStream` (`EventSource`
  cannot POST or send `Authorization`). SSE, no WebSockets (the roadmap allows either).
- Loading ("Thinking…"), incremental text, Stop (abort keeps the partial text, marked stopped),
  errors (terminal error frame, HTTP error before streaming, dropped connection) keep any partial
  text and offer "Try again"; leaving the page or starting a new conversation aborts the request.
- **No automatic reconnection:** the call is a non-idempotent POST that costs tokens, and the server
  rolls back an interrupted turn, so a silent resend could duplicate work. Retry is explicit.
- nginx: `proxy_buffering off` on `/api/` so events are not held back. The multi-agent workflow
  stays available in a mode selector; Streamlit is unchanged.

## Consequences

- Existing databases need `alembic upgrade head` (0008) for memory; without it only the memory
  endpoints and the agent's memory step fail (recall failures degrade to "no notes", saves fail as
  tool errors, `/memories` returns 500). **Apply only after explicit approval and a backup.**
- Memory is not yet exposed in the React UI (API only).
- The agent stream still delivers its final answer as one chunk (ADR 008); only the RAG path
  streams token by token.

## Verification

Offline, run: filter validation and SQL (bound parameters, after the scope), citation unit tests
including split-across-chunks equivalence, service-level citation tests, a citation-validity
evaluation metric over scripted answers, the real memory repository/service over SQLite (creation,
dedup, expiry, recall ranking and bounds, isolation across users, administrators and
organizations, mutation-checked), tool budget/failure tests, HTTP tests of `/memories`, migration
0008 SQL (only `CREATE TABLE`/`CREATE INDEX`, names match the model, downgrade drops one table),
SSE parser and Copilot UI tests (incremental text, completion, errors, retry, stop, unmount).
Not verified: PostgreSQL behavior of the new constraints (`tests/integration/test_agent_memory.py`,
the new filter tests in `test_data_isolation.py` and the 0008 steps in `test_ownership_migration.py`
are written, unrun), a real browser against a real stream through nginx, a live model's citation
behavior.
