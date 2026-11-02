# Security architecture and hardening

This page describes the trust boundaries of AegisAI and the controls added by the Phoenix security
remediation (findings AIGSEC-001 to AIGSEC-016). For each control it says what it does, how to
configure it, and what it does **not** do. Passing tests prove the behaviour the tests check;
they do not make a deployment production-ready on their own (see "Remaining limitations").

## Trust boundaries

| Boundary | Trusted side | Untrusted input | Main controls |
|---|---|---|---|
| Browser → API | the API | every request | OIDC bearer token on every business route (Keycloak, PKCE public client, tokens in `sessionStorage`); per-user access scope in every repository query; rate limits; input bounds |
| API → model | system prompt and policy | retrieved documents, tool results, remote-agent answers, saved notes | all of these are passed as labelled data, never as instructions; the output guard on what comes back |
| Model → tools | tool code | the model's tool calls and arguments | allowlisted tools, schema validation, step and tool-call limits, memory-write guard |
| Server → A2A / MCP | configured agents and the in-process MCP server | their responses | exact-origin allowlist, size and time limits, in-process MCP transport only |
| Upload → parser | the server process | the file | size, type and expansion limits, and parsing in a separate killable process |
| Services → data stores | the backend | the network | localhost-only ports (Compose), NetworkPolicy (Kubernetes), Redis password |

## Documents: ownership and visibility (AIGSEC-001)

- Owners can read their own documents. Members of the same organization can read a document only
  when its visibility is `organization`. Nothing crosses organizations.
- **Only the owner can share a document with the organization.** An administrator can delete a
  member's document or make it private, but an attempt to share it is refused with 403 and changes
  nothing. Previously an administrator could make a private document readable this way.
- Every visibility change is audited (`document.visibility_changed`) with the actor, the outcome
  (`success`, `not_found` or `forbidden`), the previous and new visibility, and whether the actor
  was the owner. The timestamp comes from the log record.
- There is no owner-consent flow for an administrator to request sharing. Adding one would be a new
  product feature.

## Agent memory: provenance and consent (AIGSEC-006)

A saved note is replayed into every later conversation, so text from a document must never become
one.

- The `save_memory` tool is **offered to the model only when the user's current message
  explicitly asks** to remember something ("remember…", "keep in mind…", "from now on…").
- Even then, the tool's code checks that the note restates the user's own words: at least 60% of
  its meaningful words must appear in that message. A note carrying a document's, a tool's or
  another agent's text is refused. The model saying "the user asked me to" counts for nothing.
  Both checks are deterministic heuristics: they limit an injection to words the user typed in
  that same message.
- Recalled notes reach the model as a delimited data block inside the user's turn, labelled with
  who saved each one. They are **never a system message**, and a note cannot close or fake the
  block.
- Users can list, edit and delete their notes, or delete all of them (`/api/v1/memories`). Notes
  belong to one user. Administrators get no access.

## Redis (AIGSEC-002, -005, -008)

| Setting | Meaning |
|---|---|
| `REDIS_URL` | address and database number (development `0`, tests `15`); no credentials in it |
| `REDIS_PASSWORD` | Redis AUTH password, passed to the client separately; **unset means no password**, the current local Redis for Windows setup |
| `RATE_LIMIT_BACKEND` | `memory` (default, this process only) or `redis` (shared by every worker and replica) |
| `RATE_LIMIT_REDIS_TIMEOUT_SECONDS` | a slower Redis reply refuses the request with 503 |

- **Docker Compose:** Postgres and Redis are published on `127.0.0.1` only. Redis refuses to start
  without `REDIS_PASSWORD`, which it reads into a private config file rather than taking it on the
  command line. The health check authenticates with `REDISCLI_AUTH`. Compose uses the shared
  (`redis`) rate limiter. Set `REDIS_PASSWORD` in your shell or the root `.env` (see
  `.env.example`) before `docker compose up`.
- **Kubernetes:** see `infra/kubernetes/README.md`, "Security settings": the `aegisai-redis-secret`
  Secret, NetworkPolicies and their CNI dependency.
- **Shared rate limits:** one atomic Lua script per check, timed by the Redis server's clock.
  Keys are `aegisai:ratelimit:<bucket>:<sha256 of organization and user>`, so no token or raw id
  appears in them, and they expire after one window. All three buckets guard expensive operations,
  so a Redis outage **fails closed** (503).
- **Local Windows development** needs no change: leave `REDIS_PASSWORD` unset and
  `RATE_LIMIT_BACKEND=memory`. Tests clear inherited settings and use Redis database 15.

## Database logging (AIGSEC-004)

The application and migration engines use `hide_parameters=True`, so a failed query's bound values
(ids, e-mail addresses, document text) are not in the error text that `logger.exception` writes.
With `hide_parameters` set, SQL echo in local development shows statements only, without values.

## Document parsing (AIGSEC-003)

PDF and DOCX text is extracted in a **separate process** (`spawn`, the method Windows uses), never
in a server thread:

- the child starts with a fresh interpreter and removes every environment variable except a few
  OS ones before it reads the file;
- after `DOCUMENT_EXTRACTION_TIMEOUT_SECONDS` (default 60) the child is terminated, then killed if
  needed, and the document is marked `FAILED` with a fixed message;
- at most `DOCUMENT_EXTRACTION_MAX_CONCURRENCY` (default 2) extractions run at once in each server
  process. A cancelled request keeps its slot until its child has gone, so abandoned work cannot
  pile up.

The existing size, page, expansion and text-length limits still apply, inside the child.

## Model cost and input bounds (AIGSEC-009)

- `LLM_MAX_INPUT_CHARS` (default 200,000, about 50,000 tokens) caps what any single model call may
  send, chat, RAG, agents, A2A specialists and multi-agent alike. An oversized prompt fails with 413
  **before** the provider is called, and is not retried.
- `ANALYST_MAX_EVIDENCE_TOTAL_CHARS` (default 50,000) caps the analyst's total evidence (422). The
  orchestrator trims its own evidence to the same cap.
- `LLM_MAX_RETRIES` is bounded to 0–5.

## Output guard (AIGSEC-015)

`app.safety.output_guard` redacts, before an answer is returned or stored:

- credential-like values: provider API keys, AWS, GitHub, Slack and Google keys, JWTs, bearer
  tokens, `password=`/`api_key:` style values, passwords inside URLs, and private-key blocks;
- by default, Luhn-valid card numbers and SSN-shaped numbers.

E-mail addresses and phone numbers are often legitimate content, so redacting them is opt-in
(`OUTPUT_GUARD_REDACT_CONTACT_DETAILS=true`). The guard can be turned off
(`OUTPUT_GUARD_ENABLED=false`).

It applies to chat, RAG, agent, multi-agent and A2A specialist answers, both streamed and not, and
to every **tool result before the model sees it**. Streamed and stored text are guarded by the same
algorithm, so they are identical: text is released at word boundaries and held back while it could
still become a match. Logs record only the kinds and the count.

It is **not** complete secret or PII detection, and it is not a hallucination or prompt-injection
defence. Citations are checked against the sources actually retrieved (`app.rag.citations`):
that proves a cited source exists, **not** that it supports the sentence (ADR 017, D-5). The
`safety` model role is not used, to avoid a second, billed and fallible model call per answer.

## A2A and MCP (AIGSEC-010, -013, -014)

- Agent Cards advertise `A2A_PUBLIC_BASE_URL`, or failing that the first `TRUSTED_A2A_AGENTS`
  entry. They never use the request's `Host` or forwarded headers.
- `ALLOWED_HOSTS` (TrustedHostMiddleware) defaults to `["*"]`. For a deployment, list its host
  names; Kubernetes HTTP probes send the pod IP as the Host unless you configure them otherwise.
- MCP: only the in-process transport is accepted. Any other transport (a URL, a command, a remote
  session) fails closed. The server's name and the identity it reports at the start of the
  session must match the allowlist. There is no remote MCP support.
- Malformed input fails one item rather than the whole task:
  - `0 ** -1` is reported as division by zero;
  - the API's expression limit equals the calculator's (200);
  - a malformed Agent Card is refused cleanly;
  - a malformed token count is recorded as unknown.

## Web front end (AIGSEC-011, -012)

- **React app (the supported, authenticated interface):** nginx sends a Content-Security-Policy
  computed at container start from the configured origins:
  - scripts, styles, images and fonts from its own origin only, with no `unsafe-inline` and no
    `unsafe-eval`;
  - `connect-src` and `frame-src` limited to its own origin, the API origin (when the API is not
    same-origin) and the sign-in provider (token requests, and the silent-renew frame);
  - `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'self'`.

  `/config.js` gets the same headers. `Strict-Transport-Security` is sent only when `HSTS_MAX_AGE`
  is set, which should happen only behind HTTPS. It never includes `includeSubDomains` or `preload`.
  TLS itself terminates in front of nginx (ingress or load balancer).
- **Legacy Streamlit UI:** it has **no sign-in**, so a backend with authentication refuses every
  request it makes, and the page says so. Untrusted text (answers, filenames, errors) is rendered
  with Markdown images neutralised, so nothing loads by itself, and raw HTML is never enabled. It
  is not a supported way to use an authenticated deployment (ADR 017, D-12).

## Supply chain (AIGSEC-007)

The security scans now block. See `docs/operations/security-scanning.md`, "Blocking policy": what
blocks for each scanner, the three exit codes, and the expiring-exception file. Actions stay pinned
to commit SHAs, and dependencies stay lockfile-based.

## Repository hygiene (AIGSEC-016)

`.gitignore` ignores `data/uploads/*` (runtime uploads) and `*.rdb` (Redis snapshots). An ignore
rule does not untrack files Git already tracks: the committed sample PDF and any other tracked
file stay tracked until someone deliberately removes them.

## Remaining limitations

- Live model behaviour against injected content has not been red-teamed. All tests use scripted
  models.
- NetworkPolicy enforcement depends on the cluster's CNI and has not been verified on a real
  cluster.
- Dependency CVE status is whatever the next blocking scan finds. The baseline is only partly
  reviewed.
- No dynamic or penetration testing has been done.
- The audit trail is ordinary structured logs, not a tamper-evident store.
- Without the shared Redis limiter, each process counts rate limits on its own (the `memory`
  backend).
