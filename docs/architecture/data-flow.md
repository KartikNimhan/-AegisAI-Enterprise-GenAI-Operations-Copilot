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

## Future data flows

Once RAG and agents are implemented, this document will describe:
ingestion (document → chunking → embedding → pgvector) and retrieval (query
→ embedding → similarity search → context assembly feeding into the chat
flow above). Neither exists yet; adding it here ahead of the code would
misrepresent the current system.
