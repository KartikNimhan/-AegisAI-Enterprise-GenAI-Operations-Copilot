# 2. LLM Gateway: a Provider-Neutral Abstraction (Groq Implemented First)

## Status

Accepted — 2026-10-03. **Updated — 2026-10-03 (Milestone 1): implemented**,
with Groq as the first (and currently only) real provider. The original
decision below to reserve the module boundary ahead of any implementation
is kept as context, since it's why the boundary looks the way it does; the
"Decision" and "Consequences" sections are updated to describe what was
actually built.

## Context

AegisAI is intended to support multiple LLM providers and multi-model
routing (e.g., routing by cost, latency, capability, or task type), plus
request/response logging, retries, rate limiting, and evaluation hooks.
Without an explicit boundary, it would be easy for provider-specific code
(SDK calls, provider-specific prompt formatting, API keys) to leak directly
into API routes or services, making it hard to add a second provider or
central routing/observability later.

Milestone 0 reserved `backend/app/llm/` as an empty placeholder for this.
Milestone 1 implements it, backed by [Groq](https://console.groq.com/) —
chosen for this first provider because its OpenAI-compatible-shaped SDK and
very low inference latency make it a fast, cheap way to validate the
gateway abstraction end-to-end before adding a second provider.

## Decision

`backend/app/llm/` is now a real, working gateway with this dependency
direction, enforced by module boundaries:

```
API (api/v1/chat.py)
  -> Service (services/chat_service.py)
    -> LLMGateway (llm/gateway.py)
      -> LLMProvider interface (llm/base.py)
        -> GroqProvider (llm/providers/groq.py)
          -> groq SDK -> Groq API
```

- **Provider interface** (`llm/base.py`): an `ABC` with `complete()` and
  `stream_complete()`. Adding OpenAI, Azure OpenAI, Gemini, Anthropic, or a
  local model later means writing a new `providers/<name>.py` that
  implements this interface — no change to the gateway, services, or
  routes. Only Groq is implemented in this milestone; no fake/stub support
  for other providers was added ahead of time.
- **`GroqProvider`** (`llm/providers/groq.py`) is the *only* module allowed
  to import the `groq` package. It translates every Groq SDK object and
  exception into the provider-neutral types in `llm/schemas.py` /
  `llm/exceptions.py` — nothing Groq-specific crosses this boundary.
- **`LLMGateway`** (`llm/gateway.py`) is what the rest of the app depends
  on. It resolves a `ModelRole` (`PRIMARY` / `FAST` / `SAFETY`, from
  `llm/schemas.py`) to a configured model name, delegates to the provider,
  retries transient failures (rate limits, timeouts, provider-unavailable)
  with exponential backoff — honoring the provider's `retry-after` when
  given — and logs structured, secret-free metadata around every call.
  Model routing is deterministic (role -> configured model name via
  environment variables); no AI-based router was added.
- **`ChatService`** (`services/chat_service.py`) is the only thing the API
  layer calls. `api/v1/chat.py` never imports `app.llm` internals beyond
  the provider-neutral exception types used for HTTP error mapping.
- Typed errors (`llm/exceptions.py`:`LLMAuthenticationError`,
  `LLMRateLimitError`, `LLMTimeoutError`, `LLMProviderUnavailableError`,
  `LLMInvalidRequestError`, `LLMProviderError`) are the only things that
  cross out of `llm/providers/`; raw `groq` exceptions never do.

See [system-design.md](../system-design.md) and
[data-flow.md](../data-flow.md) for the full request/streaming flow and
[docs/development/setup.md](../../development/setup.md) for how to run a
real request locally.

## Consequences

- **Positive**: no provider lock-in — `LLMGateway`, `ChatService`, and the
  API routes have zero references to `groq`. Adding a second provider is
  additive (a new `providers/<name>.py` plus a routing/selection knob), not
  a rewrite.
- **Positive**: retries, timeouts, and structured logging are centralized
  in one place (`LLMGateway._with_retries`) rather than duplicated per
  provider or call site.
- **Positive**: `GROQ_API_KEY` is optional at the configuration level — the
  app starts and the full test suite passes without one (the Groq client is
  constructed lazily, on first real call, not at import/startup time).
- **Negative**: model routing is a static, deterministic mapping
  (role -> env-configured model name) with no cost/latency-aware or
  AI-based routing — intentionally deferred past this milestone.
- **Negative**: Structured Outputs (JSON schema mode) is wired through as a
  pass-through `response_format` parameter but not yet exercised by any
  caller, and Groq does not support it together with streaming.

## Related

- [001-modular-monolith.md](001-modular-monolith.md)
- [003-vector-store.md](003-vector-store.md)
