# 4. Conversation Persistence and Prompt Management

## Status

Accepted — 2026-10-03

## Context

Milestone 1 made every LLM call go through `LLMGateway`, but each call was
stateless: one user message in, one completion out, nothing remembered.
Milestone 2 turns that into a real conversational application: conversation
history needs to be persisted, replayed into subsequent prompts, and
returned to clients, without introducing RAG, agents, or any memory beyond
plain conversation history.

Two sub-decisions were needed: how conversations/messages are stored, and
how the "system + history + new message" prompt gets assembled without
hardcoding that structure inside `ChatService`.

## Decision

### Persistence: two tables, a repository layer, atomic turns

`conversations` and `messages` (see
[system-design.md](../system-design.md#conversation-persistence) for the
schema) are added via Alembic migration `0002`. `app.db.repositories`
(`ConversationRepository`, `MessageRepository`) are the only code that
issues SQLAlchemy queries; `ChatService` and `ConversationService` depend
on these repositories, never on `AsyncSession` directly in business logic.

A chat turn — the user's message and the assistant's reply — is persisted
**atomically**, in one request-scoped transaction
(`app.db.session.get_session`: commit on success, rollback on any
exception). If the LLM call fails, nothing is persisted for that turn,
including the user's message. This was a deliberate choice over persisting
the user message independently: it avoids orphaned user messages with no
reply cluttering history, and it composes cleanly with a single
request-scoped session rather than needing per-step commits. The client
can simply retry.

This is simple for the non-streaming endpoint (the whole handler runs,
then the session commits), but not for streaming: `api/v1/chat.py`
deliberately catches `LLMError` inside the SSE generator and turns it into
a clean terminal event rather than re-raising, so the response doesn't
just cut off mid-stream — but that means the exception never reaches
`get_session`'s rollback. `ChatService.stream_message` therefore calls
`await self._session.rollback()` itself before re-raising internally, so
the (already-flushed) user message is discarded before the clean SSE error
event is produced. This was verified empirically, not assumed: see the
commit introducing this milestone for the experiments confirming (a)
FastAPI keeps a `yield`-dependency alive for a `StreamingResponse`'s full
body, including code after the last `yield`, and (b) committing a session
after an explicit rollback with no further changes is a safe no-op.

### Prompt management: a small builder, not a framework

`app.prompts` (`templates.py`, `builder.py`, `schemas.py`) assembles
`[system message, ...history, new user message]` via `PromptBuilder`,
rather than `ChatService` concatenating strings/messages inline. Each
system prompt is a versioned `PromptTemplate` (`id`, `version`, `text`) —
no templating engine, no prompt database. This is intentionally the
minimum that supports future growth (different prompts per use case,
versioning, eventually RAG/agent prompts) without a rewrite: a new use
case adds a new `PromptTemplate` and, if needed, a `PromptBuilder`
variant — `ChatService` and the API are unaffected either way.

System prompts are **not** persisted as messages — they're static per
template version, regenerated fresh each turn from `templates.py`, not
conversation-specific data. Only user and assistant turns are written to
`messages`.

### Role representation

`app.domain.enums.MessageRole` (persistence) and `app.llm.schemas.ChatRole`
(prompt) are two separate `StrEnum`s with identical values, not one shared
enum. `domain/` must not depend on `llm/` (the dependency direction is
`llm` -> ... -> `domain`, never the reverse — see
[001-modular-monolith.md](001-modular-monolith.md)), so sharing one enum
would mean one of the two layers importing from the other. `PromptBuilder`
is the one place that bridges them. The `messages.role` column uses
`sa.Enum(..., native_enum=False, create_constraint=True)` — a `VARCHAR` +
`CHECK` constraint rather than a Postgres native `ENUM` type, so adding a
role later is a normal column-constraint migration rather than the sharper-
edged `ALTER TYPE ... ADD VALUE`.

## Consequences

- **Positive**: `ChatService` orchestrates (resolve/create conversation,
  build prompt, call gateway, persist) without containing any SQL or
  prompt-string construction itself — both are swappable in isolation.
- **Positive**: the atomic-turn guarantee means conversation history is
  never left in a half-written state after a failed or interrupted
  request, verified by both a unit test (fakes) and a real-database
  integration test that exercises the actual commit/rollback dependency.
- **Negative**: a failed turn with a provided `conversation_id` still
  shows no trace of the attempt (not even the user's message), which is
  simple but means a client-side "your message" bubble has to be
  speculative/local until a response arrives — acceptable for this
  milestone's scope (no frontend chat UI yet).
- **Negative**: `ChatService` now depends on an `AsyncSession` directly
  (for the explicit streaming-path rollback), which is a narrower
  exception to "repositories own all DB access" than the rest of the
  codebase — justified because transaction-boundary control is a unit-of-
  work concern that belongs to the orchestrating service, not to any one
  entity's repository.

## Related

- [001-modular-monolith.md](001-modular-monolith.md)
- [002-llm-gateway.md](002-llm-gateway.md)
