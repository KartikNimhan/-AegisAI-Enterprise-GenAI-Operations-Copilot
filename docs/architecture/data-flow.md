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
   │  {"message": "...", "model_role": "primary"}
   ▼
api/v1/chat.py (create_chat_completion)
   │  thin: builds nothing, just forwards to the service
   ▼
services/chat_service.py (ChatService.complete)
   │  wraps the message as a single ChatMessage(role=user)
   ▼
llm/gateway.py (LLMGateway.chat_completion)
   │  1. resolve_model(role)  — e.g. PRIMARY -> PRIMARY_LLM_MODEL
   │  2. call provider.complete(...), retrying transient failures
   │     (rate limit / timeout / provider-unavailable) with backoff
   │  3. log structured metadata (provider, model, latency, token
   │     counts, success/failure) — never the prompt, response, or key
   ▼
llm/providers/groq.py (GroqProvider.complete)
   │  the only module allowed to import `groq`
   │  builds kwargs, omitting unset params (not sending explicit nulls)
   ▼
groq SDK (AsyncGroq.chat.completions.create)
   │  HTTPS
   ▼
Groq API
```

The response is normalized at the `GroqProvider` boundary into
`CompletionResponse` (`content`, `model`, `provider`, `finish_reason`,
`usage.{input,output,total}_tokens`, `request_id` — populated from Groq's
`x_groq.id` when present, else the completion `id`) before it travels back
up through the gateway and service unchanged. The API layer wraps it in
`ChatCompletionResponse` (same shape) and returns `200`.

**Error path**: any Groq SDK exception is translated to a typed `LLMError`
subclass inside `GroqProvider` (e.g. `groq.RateLimitError` ->
`LLMRateLimitError`) before it ever leaves `llm/providers/`. `LLMGateway`
retries the transient ones; whatever reaches the API layer is mapped to an
HTTP status by `core/exceptions.py`'s registered handlers
(`LLMRateLimitError` -> 429, `LLMTimeoutError` -> 504,
`LLMAuthenticationError` / `LLMProviderUnavailableError` -> 503,
`LLMInvalidRequestError` -> 400, anything else -> 502) and returned as the
app's standard `{"error": {"code", "message", "request_id"}}` envelope. The
raw `groq` exception and the provider's own error detail never reach the
HTTP response.

## `POST /api/v1/chat/completions/stream` (SSE)

Same path through `ChatService` / `LLMGateway` / `GroqProvider`, but
`stream_complete` is an async generator: `GroqProvider` requests
`stream=True` and `stream_options={"include_usage": True}` from Groq (so
token usage is available on the final chunk) and yields a normalized
`StreamChunk` (`delta`, `model`, `finish_reason`, `is_final`, `usage`,
`request_id`) per server-sent event from Groq.

`api/v1/chat.py` wraps this in a `StreamingResponse`
(`media_type="text/event-stream"`), emitting one `data: <StreamChunk JSON>`
line per chunk, a final `data: [DONE]`, and — if an `LLMError` is raised
mid-stream — a terminal `data: {"error": {"code", "message"}}` event
instead of raising. This last point matters: HTTP headers and the `200`
status are already committed by the time the first chunk is sent, so a
provider failure partway through can't become a 4xx/5xx; the only honest
option is a structured error event on the stream itself, which is why the
streaming endpoint has its own error-handling path distinct from the
non-streaming one. `LLMGateway` does not retry mid-stream failures, for the
same reason: a retry would risk emitting duplicate partial output the
client may have already rendered.

## Future data flows

Once RAG and agents are implemented, this document will describe:
ingestion (document → chunking → embedding → pgvector) and retrieval (query
→ embedding → similarity search → context assembly feeding into the chat
flow above). Neither exists yet; adding it here ahead of the code would
misrepresent the current system.
