# 14. Rate Limits and Audit Events

> **Milestone numbering.** Milestone numbers in this document use the project's earlier
> working numbering, not the [Official Project Roadmap](../../../README.md#official-project-roadmap).
> They record what was built under that numbering and are not redefined by the roadmap.

## Status

Accepted — 2026-10-21. Implemented and verified offline (unit tests with a fake clock, fake
services and a recording logger). Not exercised against a running stack.

## Context

After authentication and data isolation (ADR 013), any signed-in user could still run an unlimited
number of language-model requests, uploads and embedding jobs, which are the operations that cost
money or CPU, and the security-sensitive actions (sharing or deleting data) left no record of who
did them.

## Decision

### Rate limits

Three buckets, each a maximum number of **admitted** requests per **user** within a **sliding
window**:

| Bucket | Routes |
|---|---|
| `llm` | chat, RAG, agent and multi-agent endpoints (plain and streaming), and the Research and Analyst agent task endpoints |
| `upload` | `POST /documents` |
| `embedding` | `POST /documents/{id}/embeddings` |

- **Configurable, not assumed.** `RATE_LIMIT_ENABLED`, `RATE_LIMIT_WINDOW_SECONDS`,
  `RATE_LIMIT_LLM_REQUESTS`, `RATE_LIMIT_DOCUMENT_UPLOADS`, `RATE_LIMIT_EMBEDDING_JOBS` and
  `RATE_LIMIT_MAX_TRACKED_KEYS` (README lists defaults). A limit of `0` switches one bucket off.
  Nonsensical values stop the application at startup. The shipped numbers are starting points for
  an operator to review, not recommendations.
- **After authentication.** The limiter is a route dependency on the authenticated principal, so
  an anonymous request is refused with 401 before it can touch anyone's budget. A refused request
  never reaches the service and is not itself counted.
- **What the caller sees.** `429`, a generic message, `Retry-After`. Never the limit, the usage, or
  anyone else's data.
- **Fail closed.** If the limiter raises, or its table of tracked users is full of live entries,
  the request is refused with `503`; it is never allowed through unmetered.
- **Event-loop atomic.** The check-and-count runs in an `async` dependency with no `await`, so two
  requests cannot interleave inside it.

**Limitation, stated plainly.** The counters live in the memory of one process. They are **not**
shared across workers, replicas or restarts: with N processes the effective limit is up to N times
the configured one, and a restart clears the counts. Sharing them (for example through Redis)
would be the next step for a scaled-out deployment; it is not implemented and no claim of
distributed enforcement is made. Also: a multi-agent request costs several `llm` admissions,
because the agent endpoints it calls over A2A with the caller's own token are themselves limited.

### Audit events

`app.core.audit.record` writes one structured log line per sensitive action: document upload,
sharing change, embedding request and deletion; conversation deletion; and each rate-limit
refusal. Each line carries the actor's user id, organization id and role, the resource type and id,
and an outcome of `success`, `not_found` or `limited`; the request id is added by the logging
configuration. An attempt on something the caller may not touch is recorded as `not_found`,
the same word the API uses, so the trail does not distinguish "missing" from "not yours" either.

The helper refuses details that look like content or credentials (file names, titles, message
text, e-mail addresses, tokens), so a careless call site cannot leak them into the logs.

These are log lines. Making them tamper-evident (shipping to write-once storage, alerting on
repeated `not_found` or `limited` outcomes) is a deployment decision, not made here.

## Consequences

- Tests share a process-wide limiter, so the test suite resets it before every test.
- Under Compose and Kubernetes the settings are passed through (`docker-compose.yml`,
  `infra/kubernetes/backend-configmap.yaml`); the defaults are the same as the application's.
- Per-process counting means these limits protect a single instance well and a scaled-out
  deployment only approximately.

## Alternatives considered

- **Redis-backed counters:** the right answer for horizontal scale, deferred: it adds a failure
  mode (Redis unavailable) that needs its own fail-closed design and a running Redis to verify.
- **Per-IP limits:** rejected as the primary key; behind proxies the address is shared or spoofable,
  and the abuse being controlled is per account.
- **A third-party limiter library:** rejected; no new dependency was warranted for three counters.

## Verification

Offline (run): the window arithmetic with a fake clock (admit, refuse, slide, independent users and
buckets, refusals not counted, zero meaning unlimited, table-full behavior), settings validation,
every expensive route asserted to be metered in the right bucket and cheap routes asserted not to be,
user isolation of budgets, 429 shape, 503 fail-closed, unauthenticated requests never touching a
budget, and each audit event's content (including that none carries a file name, e-mail or token).
Not verified: behavior under real concurrent load, multi-process behavior, and a running deployment.
