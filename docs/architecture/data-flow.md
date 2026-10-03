# Data Flow

## `GET /health/ready`

Worth documenting precisely because `/health/ready` is what production
orchestrators (Kubernetes, load balancers, Docker Compose health checks)
use to decide whether to route traffic to an instance.

```
Client / orchestrator
   │  GET /health/ready
   ▼
FastAPI route (api/v1/health.py)
   │
   ├──▶ app.db.session.check_database()
   │        │  create_async_engine(...).connect()
   │        │  SELECT 1   (timeout: 2s)
   │        ▼
   │     PostgreSQL
   │
   └──▶ app.db.redis.check_redis()
            │  redis.asyncio.Redis(...).ping()   (timeout: 2s)
            ▼
         Redis
```

Both checks run against the same long-lived engine/connection pool used by
the rest of the application (not a separate throwaway connection path), so
the readiness check reflects the same connectivity the app would actually
use to serve a real request.

- If both checks succeed within their timeout: respond `200`, status
  `ready`.
- If either fails or times out: respond `503`, status `degraded`, with the
  specific dependency marked `unavailable` in the response body so an
  operator can tell which dependency is at fault without checking logs.

No request body, user data, or business entities are involved — this
endpoint takes no input and returns only connectivity status. Groq is
deliberately **not** part of this check: it's an external, pay-per-call
third party, not infrastructure this process owns, so a Groq outage
surfaces as a 503 on the chat endpoints themselves (see below) rather than
making the whole app report "not ready".

## `POST /api/v1/chat/completions` (non-streaming)

```
Client
   │  POST /api/v1/chat/completions
   │  {"conversation_id": null | "<uuid>", "message": "...", "model_role": "primary"}
   ▼
api/v1/chat.py (create_chat_completion)
   │  thin: forwards to the service, wraps the result
   ▼
services/chat_service.py (ChatService.send_message)
   │  1. resolve-or-create the conversation
   │     - conversation_id omitted  -> create one (title = first ~80
   │       chars of the message)
   │     - conversation_id given    -> load it, or raise NotFoundError
   │       (-> HTTP 404) if it doesn't exist
   │  2. load prior messages (MessageRepository.list_by_conversation,
   │     ordered by created_at)
   │  3. build the prompt (PromptBuilder.build): [system, ...history, new
   │     user message] — see "Prompt construction" below
   │  4. persist the user message (MessageRepository.add, flush only)
   │  5. call LLMGateway.chat_completion(model_role, prompt)
   │  6. persist the assistant message: content, model, provider,
   │     finish_reason, request_id, input/output/total tokens — only the
   │     fields the provider actually returned
   │  7. touch the conversation's updated_at
   ▼
llm/gateway.py (LLMGateway.chat_completion)
   │  resolve_model(role), call provider, retry transient failures,
   │  log structured metadata — never the prompt, response, or key
   ▼
llm/providers/groq.py (GroqProvider.complete) -> groq SDK -> Groq API
```

The response is normalized at the `GroqProvider` boundary into
`CompletionResponse` before traveling back up through the gateway and
service unchanged. The API layer returns `ChatCompletionResponse`
(`conversation_id`, `content`, `model`, `provider`, `finish_reason`,
`usage`, `request_id`) with `200`.

**Atomicity**: steps 1–7 run inside one database transaction
(`app.db.session.get_session`: commit only after the whole request
handler returns successfully, rollback on any exception). If step 5
raises, the exception propagates straight past the route (which has no
try/except around the service call) to that dependency's rollback — so a
failed turn leaves *nothing* persisted, not even the user's message from
step 4. The client gets a mapped error response and can simply retry; see
[ADR 004](decisions/004-conversation-persistence.md) for why this was
chosen over persisting the user message independently.

**Error path**: any Groq SDK exception is translated to a typed `LLMError`
subclass inside `GroqProvider` (e.g. `groq.RateLimitError` ->
`LLMRateLimitError`) before it ever leaves `llm/providers/`. `LLMGateway`
retries the transient ones; whatever reaches the API layer is mapped to an
HTTP status by `core/exceptions.py`'s registered handlers
(`LLMRateLimitError` -> 429, `LLMTimeoutError` -> 504,
`LLMAuthenticationError` / `LLMProviderUnavailableError` -> 503,
`LLMInvalidRequestError` -> 400, `NotFoundError` -> 404, anything else ->
502) and returned as the app's standard
`{"error": {"code", "message", "request_id"}}` envelope. The raw `groq`
exception, the provider's own error detail, and raw database errors never
reach the HTTP response.

## `POST /api/v1/chat/completions/stream` (SSE)

Same steps 1–4 as above, then:

```
services/chat_service.py (ChatService.stream_message)
   │  async for chunk in LLMGateway.stream_chat_completion(...):
   │      accumulate chunk.delta into one string
   │      yield StreamTurnChunk(conversation_id, chunk)   -> to the route
   │  (on success, after the loop) persist ONE assistant message with the
   │  full accumulated content + whatever usage/model/finish_reason the
   │  final chunk carried; touch the conversation
   ▼
llm/providers/groq.py (GroqProvider.stream_complete)
   │  requests stream=True and stream_options={"include_usage": True}
   │  (so usage is available on the final chunk), yields a normalized
   │  StreamChunk per server-sent event from Groq
```

`api/v1/chat.py` wraps the chunks in a `StreamingResponse`
(`media_type="text/event-stream"`), emitting one
`data: <ChatCompletionStreamChunk JSON>` line per chunk (repeating
`conversation_id` on every chunk, since a brand-new conversation's id isn't
known before the first one), a final `data: [DONE]`, and — if an
`LLMError` is raised mid-stream — a terminal
`data: {"error": {"code", "message"}}` event instead of raising. This last
point matters: HTTP headers and the `200` status are already committed by
the time the first chunk is sent, so a provider failure partway through
can't become a 4xx/5xx; the only honest option is a structured error event
on the stream itself. `LLMGateway` does not retry mid-stream failures, for
the same reason: a retry would risk emitting duplicate partial output the
client may have already rendered.

**Persistence is never per-token.** Only one assistant `Message` row is
written, after the stream completes, with the fully accumulated content —
not one row per chunk.

**Atomicity under streaming** is trickier than the non-streaming case,
because the route deliberately *catches* `LLMError` to produce a clean SSE
event rather than letting it propagate — which means the request-scoped
session's own rollback-on-exception never fires. `ChatService.stream_message`
handles this itself: on `LLMError`, it calls `await self._session.rollback()`
directly (discarding the already-flushed user message) before re-raising
internally, so by the time the route's `except LLMError` catches it and
returns normally, there's nothing left for the ambient session to commit
except a no-op. See [ADR 004](decisions/004-conversation-persistence.md)
for the reasoning and the experiments that confirmed this works correctly
with FastAPI's dependency lifecycle.

## `GET /api/v1/conversations/{conversation_id}`

```
Client
   │  GET /api/v1/conversations/{id}
   ▼
api/v1/conversations.py (get_conversation)
   │  404 if the service returns None
   ▼
services/conversation_service.py (ConversationService.get_conversation)
   ▼
db/repositories/conversation_repository.py (get_with_messages)
   │  SELECT ... with selectinload(Conversation.messages)
   │  (messages come back pre-ordered by created_at — see the
   │  relationship's order_by in domain/models/conversation.py)
   ▼
PostgreSQL
```

Returned as `ConversationDetail` (`id`, `title`, `created_at`,
`updated_at`, `messages: [...]`) — never the raw ORM object. `GET
/api/v1/conversations` and `DELETE /api/v1/conversations/{id}` follow the
same thin API -> service -> repository path.

## `POST /api/v1/documents` (upload)

```
Client
   │  POST /api/v1/documents  (multipart/form-data)
   ▼
api/v1/documents.py (upload_document)
   │  bounded read: file.read(max_size + 1) — never buffers more than
   │  that, regardless of what the client claims or sends
   ▼
services/document_service.py (DocumentService.upload)
   │  1. sanitize_filename, determine_document_type, validate_size,
   │     validate_content_type, validate_magic_bytes
   │     (any failure here -> DocumentValidationError -> HTTP 400,
   │      nothing stored, nothing in the database)
   │  2. compute SHA-256 checksum
   │  3. look up by checksum — a match returns the EXISTING document
   │     immediately (is_duplicate: true, HTTP 200, no new storage or
   │     processing)
   │  4. _create_and_store: insert Document(status=UPLOADED), flush to
   │     get its id, save the raw bytes via DocumentStorage keyed by
   │     that id, COMMIT  <-- first of two commits, see below
   │  5. _process: status -> PROCESSING, then:
   ▼
documents/extractors/{pdf,docx,text,markdown}.py (via get_extractor)
   │  the only code allowed to import pypdf / python-docx
   │  returns ExtractionResult(pages=[...], metadata={...})
   │  (offloaded via asyncio.to_thread — CPU-bound, not I/O)
   ▼
documents/normalization.py (normalize_text, per page)
   ▼
documents/metadata.py (build_document_metadata)
   ▼
documents/chunking/recursive.py (RecursiveChunker.chunk, per page)
   │  deterministic chunk ids via documents/chunk_ids.py
   ▼
db/repositories/document_chunk_repository.py (add_all, inside a SAVEPOINT)
   │  status -> PROCESSED (+ chunks) or FAILED (+ safe error_message,
   │  no chunks — the SAVEPOINT rolls back just the failed chunk insert,
   │  not the UPLOADED row from step 4), COMMIT  <-- second commit
   ▼
PostgreSQL + local disk (data/uploads/, via DocumentStorage)
```

**Why two commits, not one** (unlike the chat flow above, which is
strictly one commit per request): by the time processing could fail, the
file is already durably on disk and the upload itself succeeded. The
`Document` row must survive that outcome either way — see
[ADR 005](decisions/005-document-ingestion.md) for the full reasoning,
including a cross-clock-source bug this design surfaced and fixed.

**Error path**: validation errors (step 1) are the only ones that become
an HTTP 4xx — they happen before anything is stored. Everything after
storage (extraction, normalization, chunking, persistence) is caught
inside `DocumentService._process` and recorded as `status: "failed"` with
a safe `error_message`; the HTTP response is still `201 Created`, since
the upload itself succeeded. The client discovers a processing failure by
reading the returned (or later re-fetched) document's `status`, not via an
error response.

## `GET /api/v1/documents/{document_id}` and `.../chunks`

Same thin API -> `DocumentService` -> repository path as conversations,
returning `DocumentResponse` / paginated `DocumentChunkResponse` — never
the raw ORM object, and never `Document.filename` (the internal storage
key); only `original_filename`. `DELETE /api/v1/documents/{document_id}`
deletes the database row first (cascading to chunks via
`ON DELETE CASCADE`), then the stored file — if file deletion fails, it's
logged but doesn't fail the request, since the record (the API's source of
truth) is already gone.

## Future data flows

Once embeddings, vector search, RAG, and agents are implemented, this
document will describe: embedding generation (chunk → embedding model →
vector → pgvector column) and retrieval (query → embedding → similarity
search → context assembly feeding into the chat flow above). None of that
exists yet; adding it here ahead of the code would misrepresent the
current system.
