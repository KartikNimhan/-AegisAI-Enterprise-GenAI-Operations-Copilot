# 11. Copilot UI/Dashboard: Frontend Architecture and Backend Boundary

## Status

Accepted — 2026-10-08

## Context

Milestones M0–M8 built a complete backend: an LLM gateway, RAG, document
ingestion, a single-agent LangGraph orchestration layer, MCP/A2A
interoperability, and a multi-agent orchestrator reached through
`POST /api/v1/multi-agent/run`. None of it had a real user-facing
interface — `frontend/streamlit/app.py` was a Milestone 0 placeholder
that only checked backend connectivity. Milestone 9 builds the Copilot
UI and an enterprise operations dashboard **on top of** those existing
APIs, without moving any orchestration/business logic into the frontend
and without replacing the existing frontend framework.

## Decision

### Frontend framework: Streamlit (reused, not replaced)

`pyproject.toml` already had a `frontend` dependency group
(`streamlit>=1.39`, `httpx>=0.27`) and a `frontend/streamlit/` directory
with a working `app.py`/`services/api_client.py` foundation. The brief is
explicit: "do not replace an existing frontend framework merely because
you prefer another one." M9 extends that same Streamlit app — a
server-rendered Python UI, not a separate JavaScript SPA — rather than
introducing React/Vue/a Node toolchain. This has a direct, favorable
consequence for the CORS question (see "CORS" below).

### Architecture

```
User
 │
 ▼
Streamlit pages (frontend/streamlit/)
 │  app.py (Copilot), pages/1_Documents.py, pages/2_Operations.py,
 │  pages/3_System_Status.py — classic Streamlit `pages/` auto-discovery,
 │  no custom navigation code needed
 ▼
services/api/ (the one place every HTTP call is made)
 │  client.py   — request_json(): the shared httpx call + error handling
 │  copilot.py  — POST /api/v1/multi-agent/run
 │  documents.py — the existing Milestone 3 document endpoints
 │  operations.py — GET /api/v1/operations/summary (new, read-only)
 │  system.py    — GET /api/v1/system/status (new, read-only)
 │  health.py    — GET /health/ready (existing, unversioned)
 ▼
FastAPI backend (unchanged M0–M8 routes, plus the two new ones above)
```

`components/response.py`/`components/errors.py` are presentation-only —
they format an already-fetched `MultiAgentRunResult`/`BackendError` into
Streamlit elements, with no HTTP calls of their own. `services/state.py`
holds the only client-side state this app keeps (see "State management").

### Why the frontend does not perform orchestration

`app.py` calls exactly one endpoint, `POST /api/v1/multi-agent/run`, and
renders exactly what it returns. There is no routing, agent-selection,
retry, or aggregation logic anywhere in `frontend/`: all of that is
`app.multi_agent.orchestrator.MultiAgentOrchestrator`'s job (Milestone 8,
see ADR 010), reached only through the one HTTP boundary. A second
orchestration layer in the frontend would duplicate that logic, let it
drift out of sync with the backend's own policy/security enforcement
(capability authorization, trusted-agent allowlists, loop prevention —
all server-side), and violate the explicit brief instruction "do not
create a second orchestration layer in the frontend." The frontend is a
thin, untrusted client over one well-defined API contract.

### API client architecture

`services/api/client.py::request_json` is the **only** function that
calls `httpx` in this codebase — every page/component goes through it (or
a thin per-resource wrapper in `copilot.py`/`documents.py`/
`operations.py`/`system.py`/`health.py`, each built directly from the
backend's own Pydantic schemas read from source, never guessed from
memory). It normalizes every failure mode — timeout, connection refusal,
an HTTP error status, a malformed/non-JSON body — into one exception type,
`BackendError(message, code, status_code)`, so UI code never inspects a
raw `httpx` exception or a Python traceback. A structured backend error
(`app.core.exceptions`'s `{"error": {"code", "message", "request_id"}}`
envelope) is parsed and its own safe `message` surfaced directly; a
connectivity-level failure the backend never got to respond to gets one
of three frontend-authored messages (`components/errors.py`). `/health/
ready`'s 503 "degraded" response is explicitly accepted as a *successful*
parse (`ok_status_codes=(200, 503)`) since that body is itself meaningful
data, not a failure to raise on.

### Copilot user flow

1. User types a message in `st.chat_input`.
2. The message is appended to client-side history and immediately shown.
3. `run_multi_agent_workflow(message)` calls the M8 endpoint once (no
   client-side routing — see above).
4. The full, already-complete response is rendered — no simulated
   token-by-token streaming (the M8 endpoint is not a streaming endpoint;
   simulating one in the browser would present a false impression of
   real-time generation the backend isn't actually doing, which the
   brief explicitly prohibits — see "Limitations" below for what a real
   streaming M8 endpoint would need).
5. The turn (including the full `MultiAgentRunResult`, or the error
   message if the call failed) is appended to history and stays visible.

### State management

The only state kept is per-browser-session chat history
(`services/state.py`, `st.session_state`) — a list of `ChatTurn`s, each
either a user message or an assistant turn carrying the parsed
`MultiAgentRunResult` (or an error string). No Redux/Zustand/global store
is introduced; `st.session_state` is Streamlit's own, already-idiomatic
mechanism, and `st.cache_data`/`st.cache_resource` were not needed since
no page performs an expensive, cacheable computation of its own — it only
fetches already-small JSON payloads.

This is also why the M8 endpoint is stateless (ADR 010: no
`conversation_id`, no server-side turn persistence) and the UI's history
is purely client-side: adding conversation persistence to M8 for the
UI's convenience would be a real backend semantics change, not "the
smallest necessary" one, and the brief explicitly says not to modify M8
semantics to make the UI easier. Each turn is an independent workflow
call; the illusion of a continuous conversation is a client-side
presentation choice, not a backend guarantee — documented here, not
hidden.

### Source/citation presentation

Source shape is **not uniform** across the three specialists (reusing
`app.api.schemas.multi_agent.MultiAgentRunResponse.sources`, a flattened
`list[dict]` tagged with `agent_name`, read directly from source): a
Research source carries `chunk_id`/`document_id`/`filename`/
`page_number`/`similarity`; a Document source carries `document_id`/
`filename`/`document_type`/`status`; an Analyst "source" is actually a
calculation (`expression`/`success`/`result`/`error`), not evidence at
all. `components/response.py::_render_source` branches on which fields
are actually present and renders only those — it never invents a
`page_number` or a `similarity` score for a source that didn't provide
one, and labels a calculation as a calculation, not a document.

### Agent/workflow transparency

`MultiAgentRunResponse.agents_used`/`status`/`duration_ms`/`token_usage`
are rendered in a collapsed "Workflow" expander, secondary to the answer.
Per-agent status uses the same vocabulary the backend returns
(`completed`/`failed`/`timeout`/`unauthorized`) — never translated into a
more "exciting" label. `workflow_id`/`correlation_id` are shown only
inside that same expander's own caption line, never prominently, per the
brief's "do not expose raw correlation IDs by default."

### Documents UI

Built directly against the existing Milestone 3 endpoints (`POST/GET/
DELETE /api/v1/documents`, `/{id}/chunks`, `/{id}/embeddings`) — no new
document-processing architecture. Upload, list (with per-document status:
uploaded/processing/processed/failed), a details expander (metadata,
chunks on demand, embedding status/trigger, delete) are all thin calls
to those existing routes.

### Operations dashboard: real data only

`GET /api/v1/operations/summary` (new, Milestone 9) is the **only**
metric source the dashboard renders — a single grouped `COUNT(*) ...
GROUP BY status` query (`DocumentRepository.count_by_status`) is the
entire new backend logic, reused as-is, no new business logic. Request/
agent-execution counts are deliberately **not shown**: Milestone 8's
orchestrator does not persist any workflow history (ADR 010 — it is
intentionally stateless), so there is no truthful source for "Copilot
requests" or "agent executions" today. Inventing one would mean adding
real backend persistence — a change well beyond "the smallest necessary
for the UI" — so the dashboard instead shows an explicit "No operational
history is available yet" note rather than a fabricated number. This is
the brief's own explicit instruction ("prefer real data over
impressive-looking fake data... omit the metric") applied literally.

### System status: live checks vs. configuration facts, labeled separately

`GET /api/v1/system/status` (new) reuses the *exact same* `check_database`/
`check_redis` functions `/health/ready` already calls — not a second,
divergent implementation of "is Postgres reachable." `llm_configured`
(`Settings.groq_api_key is not None`) and `trusted_a2a_agents`/
`mcp_server` are configuration facts, not live probes — a live Groq/MCP/
A2A call on every status-page load would cost a real API call (and
latency) just to render a page, out of proportion for this milestone.
The UI renders these as two visually distinct sections ("Live
connectivity" vs. "Configuration") so neither is ever presented as a
live health check it isn't — directly satisfying "do not claim healthy
merely because the frontend loaded."

### Security boundaries

- The frontend never accepts an MCP/A2A endpoint, an arbitrary tool
  selection, or any other backend-internal control from the user — there
  is no such field anywhere in the UI, matching the backend's own M7/M8
  guarantee that no such input ever reaches `A2AClient`/the MCP client.
- Chain-of-thought, system prompts, raw tool arguments, and raw backend
  exception tracebacks are never rendered — the UI only ever has access
  to `MultiAgentRunResponse`'s already-sanitized fields and
  `BackendError`'s already-safe message; there is no code path that could
  leak more even by a future bug, since nothing richer is ever fetched.
- `request_id`/credentials/API keys are never displayed; `/api/v1/system/
  status` reports *whether* an LLM key is configured, never the key
  itself (it is a `pydantic.SecretStr` server-side and was never
  serialized to begin with — see `app.config.Settings`).

### CORS

Streamlit is a **server-rendered** Python app: `services/api/client.py`'s
`httpx` calls run in the Streamlit server process, not as a browser
`fetch()` from JavaScript — there is no cross-origin browser request to
the FastAPI backend at all, so CORS is not applicable to this frontend/
backend pairing today. `Settings.cors_origins` (defaulting to
`["http://localhost:8501"]`, Streamlit's own default port) already
existed before this milestone but was — and remains — unused:
`CORSMiddleware` was never wired into `app.main.create_app()`. This is
left as-is (not removed, not wired up) rather than guessed at: wiring up
unused middleware "just in case" for a frontend architecture that
doesn't need it would be speculative, and removing a setting a future
JS-based frontend might legitimately need is also not this milestone's
call to make. `AEGIS_BACKEND_URL`/`AEGIS_BACKEND_TIMEOUT_SECONDS` (both
already-existing/newly-documented env vars, never a URL the user can
type into the UI) are how the frontend is pointed at a backend running on
a different host/port.

### Responsive design and accessibility

Streamlit's built-in layout (`layout="wide"`, `st.columns`) reflows
reasonably down to a narrow viewport without custom CSS — no separate
mobile app or bespoke responsive framework was built, matching "do not
spend the milestone building a separate mobile application." Every
interactive control is a native Streamlit widget (`st.button`,
`st.chat_input`, `st.file_uploader`, `st.expander`) — these are already
real HTML `<button>`/`<input>`/labeled elements with keyboard support and
visible focus states out of the box; no custom unlabeled `<div>`
pseudo-controls were introduced, and status is always paired with text
(`"✅ Completed"`, `"❌ Failed"`), never color alone.

### Visual design

Deliberately restrained: Streamlit's default theme, `st.metric`/
`st.container(border=True)`/`st.expander` for structure, no custom CSS
injection, no gradients, no "AI magic" visuals, matching the brief's
explicit "avoid flashy gradients, excessive animation, meaningless
charts, crypto-dashboard aesthetics." The one chart
(`st.bar_chart(documents_by_status)`, Operations page) is populated only
from the real summary endpoint — never shown with placeholder data.

### Backend additions (the only two)

`GET /api/v1/operations/summary` and `GET /api/v1/system/status` — both
read-only, both reusing existing checks/queries (`check_database`/
`check_redis`/a single new `DocumentRepository.count_by_status` grouped
`COUNT` query), added only because the UI genuinely needed information
no existing endpoint exposed. No other backend route, schema, or M8
semantic was touched.

### Limitations

- No real-time/streaming Copilot response: the M8 endpoint is request/
  response only. A future streaming variant (`POST /api/v1/multi-agent/
  run/stream`, mirroring the M6 agent's own `/run/stream` SSE pattern)
  would need the orchestrator to emit incremental per-agent events — not
  built here, to avoid both over-engineering this milestone and
  simulating a streaming experience the backend doesn't actually provide.
- No persisted conversation history: a browser refresh loses the
  client-side chat history (`st.session_state` is per-session). Backend
  conversation persistence for M8 is a real feature gap, not a UI bug —
  tracked as future work, not solved here (see ADR 010's own "Future
  scaling considerations" for the parallel gap on the orchestration
  side).
- No "Copilot requests"/"agent executions" dashboard metrics, for the
  reason given above (no persisted workflow history yet).
- CORS/`cors_origins` remains an unused, pre-existing setting — revisit
  if/when a JavaScript-based frontend is ever introduced.

## Testing

- **API client** (`frontend/streamlit/tests/test_api_client.py`):
  success, the structured error envelope, network failure, timeout, an
  accepted non-2xx status, a malformed response — against a mocked
  `httpx` transport, no real network.
- **Copilot** (`test_copilot.py`): empty state, a successful response,
  sources, agent/workflow status, a partial workflow, a failed workflow
  (never fabricating an answer), a backend error, the "new conversation"
  action, and one consolidated E2E-style happy-path test (question ->
  answer -> sources -> agent status, all visible) — all via
  `streamlit.testing.v1.AppTest` running the real `app.py` script, with
  `services.api.copilot.run_multi_agent_workflow` monkeypatched to
  deterministic, backend-shaped data. No real Groq/network/E2E browser
  framework needed.
- **Documents** (`test_documents.py`): a successful list, the empty
  state, an API failure, and per-status rendering.
- **Operations** (`test_operations.py`): real data as metrics, the
  explicit empty state, an API failure, and a guard that no fabricated
  request/execution metric is ever rendered.
- **System Status** (`test_system_status.py`): the healthy/available and
  degraded/unavailable states, an API failure, and a guard that no
  blanket "healthy" claim is ever rendered.
- **Backend** (`backend/tests/unit/api/test_operations_endpoint.py`,
  `test_system_endpoint.py`): the two new endpoints, with the
  `DocumentRepository`/`check_database`/`check_redis` dependencies
  faked/monkeypatched — no real Postgres/Redis required.
- All M0–M8 backend tests continue to pass unchanged.

## Consequences

- **Positive**: reusing Streamlit (rather than introducing a JS
  toolchain) means M9 ships with zero new infrastructure, zero new
  runtime dependencies beyond what the `frontend` dependency group
  already declared, and no CORS configuration to get right — the
  server-rendered architecture sidesteps an entire category of
  frontend/backend integration risk other frameworks would introduce.
- **Positive**: centralizing every HTTP call in `services/api/client.py`
  means every page gets the same error handling for free, and the two
  genuine bugs this kind of pattern tends to surface (a malformed
  response, an unexpected non-2xx status) are handled in exactly one
  place, tested once.
- **Positive**: building each API module's dataclasses directly from the
  backend's own Pydantic schemas (read from source, not memory) caught
  the exact field names/shapes on the first pass — no silent field
  renaming anywhere in this milestone's frontend code.
- **Negative**: the per-session, client-side-only chat history means a
  page refresh loses the visible conversation (though every individual
  workflow result is still fully derivable by re-asking, since M8 is
  stateless either way).
- **Negative**: the Operations dashboard is smaller than the brief's
  "suggested" card list (no request/execution counts) — a deliberate,
  documented omission rather than a fabricated one, but a real gap for
  anyone expecting those numbers until M8 gains workflow persistence.

## Related

- [010-multi-agent-architecture.md](010-multi-agent-architecture.md)
  (the M8 orchestrator this UI calls through exactly one endpoint, and
  the statelessness this ADR's "State management"/"Operations dashboard"
  sections both depend on)
- [008-agent-architecture.md](008-agent-architecture.md) (the M6
  `/run/stream` SSE pattern a future real Copilot streaming endpoint
  would mirror)
