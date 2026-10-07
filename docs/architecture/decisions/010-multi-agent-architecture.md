# 10. Multi-Agent Orchestration: Supervisor, Specialists, and Aggregation

## Status

Accepted — 2026-10-07

## Context

Milestone 7 built one remote Research Agent reached through a real A2A
boundary — a reference implementation demonstrating "orchestrator talks to
one specialized agent," deliberately not a multi-agent system. Milestone 8
is explicitly about learning and demonstrating **multi-agent
orchestration** on top of that same boundary: a supervisor/orchestrator
routes a request to one or more specialized agents, runs independent
agents in parallel, runs a synthesis step sequentially after them when
needed, and aggregates a final answer — while staying small, deterministic
where possible, and explainable in an interview. It explicitly does
**not** build a giant autonomous-agent framework, a distributed task
queue, a message broker, or an agent marketplace.

## Decision

### Why multi-agent architecture exists (vs. one giant agent)

The M6 agent is already capable of tool-calling its way through a RAG
question or a calculation. What a single agent's tool-calling loop does
*not* give you is **separation of concerns with an independent trust/
scope boundary per specialist**: a Research Agent's system prompt, context
budget, and allowed tools are not the same as an Analyst Agent's, and
letting one large agent hold every capability means every prompt-injection
surface and every tool failure mode is shared across all of them. Splitting
into specialized agents reached through A2A means each one can be reasoned
about, tested, and evolved independently — the same argument for
microservices applied to agent *capability* boundaries rather than service
boundaries, and exactly what A2A is designed to standardize.

### Supervisor/orchestrator pattern

```
User
 │
 ▼
POST /api/v1/multi-agent/run  (api/v1/multi_agent.py — thin)
 │
 ▼
MultiAgentOrchestrator (app/multi_agent/orchestrator.py)
 │  1. route(question)              -> RoutingDecision (deterministic)
 │  2. authorize + depth/delegation-limit check
 │  3. run tier-1 agents (parallel if >1, sequential if 1)
 │  4. run Analyst (sequential, if synthesis/calculation needed)
 │  5. aggregate -> final answer
 ▼
A2AClient.submit_task(...)  — the ONLY path to a specialist, never a
                              direct import of its service class
 │
 ▼
Research Agent | Document Agent | Analyst Agent  (each its own A2A
                                                   endpoint, Agent Card,
                                                   task lifecycle)
```

The orchestrator contains **no domain-specific research/document/
calculation logic** — that stays inside each agent's own service
(`ResearchAgentService`, `DocumentAgentService`, `AnalystAgentService`),
each already a Milestone 7-style A2A-exposed agent. The orchestrator only
decides *which* specialists to call, *in what order*, and how to combine
their results.

### Specialized agents (exactly three, as required)

- **Research Agent** (Milestone 7, unchanged): retrieval + synthesis over
  the knowledge base via `RetrievalService`/`LLMGateway`. Returns
  `ResearchResult` (answer, sources, `token_usage`).
- **Document Agent** (new, `app/a2a/document_agent.py`): given one or more
  document ids, returns safe metadata for each via `DocumentRepository` —
  the exact same read `get_document_metadata`/the MCP server's adapter
  already use, not a new query. **Deterministic, no LLM call**: a metadata
  lookup has no synthesis step of its own; comparing/synthesizing across
  a document's metadata and another agent's findings is the Analyst's job.
  "Evidence metadata, not an invented confidence score" (see "Why no
  confidence score" below) applies here too — the result is exactly what
  was found/not found, nothing inferred.
- **Analyst Agent** (new, `app/a2a/analyst_agent.py`): safe arithmetic
  (reuses `CALCULATOR_TOOL.executor`/`CalculatorArgs` — no second
  implementation) and, when other agents' evidence is supplied, a
  synthesis step via `LLMGateway`. **Never reaches any external system of
  its own** — no `RetrievalService`/`DocumentRepository`/A2A client — it
  only ever reasons over `expressions`/`evidence` the orchestrator hands
  it, enforcing "context isolation" structurally, not by convention.

### Why no invented confidence score

The brief explicitly warns against unsupported confidence scores. None of
`RetrievalResult`/`CompletionResponse`/the calculator provide a calibrated
confidence number, so none is invented here either. What each specialist
returns instead is **evidence metadata** that already exists:
`ResearchResult.sources` (chunk id, filename, page, cosine similarity —
a real, computed number, not a confidence label), `DocumentAgentResult
.documents` (exact metadata found or explicitly listed as missing), and
`CalculationResult.success`/`.error` (did the expression evaluate, plain
and simple). The final aggregated answer distinguishes confirmed evidence
from an agent's own conclusion by which agent produced which part of the
answer (see "Aggregation" below), not through a fabricated certainty score.

### Agent capability model

```
app/multi_agent/capabilities.py

CAPABILITY_REGISTRY: dict[agent_key, AgentSpec]
  AgentSpec(agent_key, expected_name_attr, card_path, capabilities,
            skill_id_by_capability)

research  -> {research}
document  -> {document_analysis}
analyst   -> {calculation, synthesis}
```

One static registry, not routing logic scattered across the codebase.
`agent_for_capability(capability)` is the single place that answers "who
provides this." An agent is only ever called when **both** this static
policy and its own independently-discovered Agent Card (fetched and
validated by `A2AClient` at call time, exactly as Milestone 7 already
does) agree on the capability/skill — a compromised or buggy Card
response alone can never grant a new capability, and a static-policy bug
alone can never bypass what an agent's own Card actually advertises.

### Agent Card (reused from Milestone 7, extended)

Only the Research Agent's card is served at the A2A well-known path
(`/.well-known/agent-card.json`) — that path is a **per-origin**
convention (one well-known document per host), and all three agents in
this milestone share an origin (the same FastAPI app). The Document and
Analyst Agent Cards are served at their own versioned convenience path
instead (`/api/v1/agents/document/card`, `/api/v1/agents/analyst/card`),
the same pattern `/api/v1/agents/research/card` already used as a
convenience alias to the well-known one. `A2AClient.fetch_agent_card_at`
(generalized from Milestone 7's `fetch_agent_card`) takes `card_path`
explicitly rather than assuming the well-known path everywhere. At
workflow start, the orchestrator does not pre-fetch every Card up front —
each specialist's Card is fetched (and validated) lazily, only when that
specialist is actually going to be called, avoiding an unnecessary round
trip for a capability a given request never needed.

### Routing

**Fully deterministic** (`app/multi_agent/router.py`): a regex/keyword
policy, not an LLM call. A `"15% of 500"`/arithmetic pattern routes to
`calculation`; a UUID (an actual `Document.id`, not an invented
`DOC-123`-style identifier, since real document ids are UUIDs) routes to
`document_analysis`; "compare"/"research"/"policy"-style language routes
to `research`; anything matching none of those — pure small talk — routes
to no specialist at all ("direct": the orchestrator answers with one
plain LLM call, no agent delegation). More than one capability, or an
explicit comparison, adds `synthesis` (routed to the Analyst). This keeps
routing **exhaustively testable without a live Groq call**
(`tests/unit/multi_agent/test_router.py`), consistent with the brief's own
warning not to claim real-model routing accuracy from a small synthetic
test set — a "hybrid" router that sometimes calls an LLM to decide routing
would make that exact claim unfalsifiable in CI. A real bug was found and
fixed during manual verification: a UUID's hyphen-joined hex groups look
exactly like a subtraction expression to a naive arithmetic regex (e.g.
the substring `152-084718340` inside a real UUID) — fixed by masking out
matched UUIDs before running the arithmetic pattern.

### Sequential workflow

`Research -> Analyst` and `Document -> Analyst` (never the reverse, see
"Workflow policy" below): the Analyst always runs **after** whichever
tier-1 specialists the request needed, consuming their answers as
`evidence` — it is the one agent capable of calculation and
cross-specialist synthesis, so it is structurally the last step, never a
source of further evidence-gathering itself.

### Parallel workflow

When a request needs more than one tier-1 specialist (e.g. Research +
Document for a comparison), both run via `asyncio.gather` — genuinely
concurrent, not serialized for no reason. Each specialist call
(`app/multi_agent/adapters.py`) **never raises** — any A2A failure or
per-call timeout is caught and turned into a structured `AgentResult`
before `gather` ever sees it, so one specialist's failure can never
cancel or corrupt an unrelated specialist's already-successful result
(verified directly: `tests/unit/multi_agent/test_orchestrator.py::
test_partial_failure_when_document_missing_but_research_succeeds`).
Concurrency is inherently bounded here — at most two tier-1 agents exist
by construction (Research, Document), so no semaphore/limiter is needed
for an unbounded fan-out that doesn't exist in this milestone's scope.

### Context isolation

`AgentContext` (`app/multi_agent/models.py`) is the *only* thing a
specialist call receives: `task_id`, `correlation_id`, `workflow_id`,
`user_question`, and only the fields that specialist actually needs
(`document_ids` for Document, `expressions`/`evidence` for Analyst) —
never the full conversation history, another agent's internal reasoning,
or unrelated database content. The Analyst's `evidence` is explicitly
just the **answer text** of whichever tier-1 specialists succeeded, not
their raw sources/metadata — a deliberate minimum, not a shortcut: the
Analyst doesn't need a document's character count to compare two answers.

### Structured results

`AgentResult` (`app/multi_agent/models.py`) is the one shape every
specialist's response is normalized into (`agent_name`, `capability`,
`status`, `answer`, `sources`, `metadata`, `error`, `duration_ms`,
`retry_count`) — regardless of which agent produced it or what its own
A2A wire schema looks like (`ResearchResult`/`DocumentAgentResult`/
`AnalystAgentResult` all differ at the protocol layer; `app/multi_agent/
adapters.py` is where each gets normalized). The orchestrator and
aggregator only ever reason about `AgentResult`, never a protocol-specific
type.

### A2A integration (no second protocol)

The orchestrator never imports `ResearchAgentService`/
`DocumentAgentService`/`AnalystAgentService` directly — every specialist
call goes through `A2AClient.submit_task` (generalized from Milestone 7's
`submit_research_task`, which is now a thin wrapper over it). `A2AClient`
gained exactly one new generic method; no new transport, no new wire
format, no second communication protocol.

### Failure handling

Every `A2AError` subtype (`A2AConnectionError`, `A2ATimeoutError`,
`A2AUntrustedAgentError`, `A2AInvalidCardError`, `A2ATaskFailedError`) and
a per-call `asyncio.TimeoutError` are caught inside `adapters.py` and
turned into a structured, never-raised `AgentResult(status=...)` — the
same "a remote failure never crashes the caller" guarantee
`ToolRegistry.execute` and the MCP client already give (Milestones 6/7).
`ResultAggregator` never fabricates a result for an agent that didn't
complete: a partial failure is surfaced as `status: "partial"` with an
explicit "(Note: `<agent>` did not complete (`<status>`).)" appended to
the answer, never silently dropped.

### Retries

Only `metadata["retryable"]` results are retried — set by `adapters.py`
only when the underlying failure was `A2AConnectionError`/`A2ATimeoutError`
(transient transport) or the adapter's own per-call `asyncio.TimeoutError`
— never for `A2AUntrustedAgentError`/`A2AInvalidCardError`/
`A2ATaskFailedError` (permanent/content-level failures, see
`app/multi_agent/policies.py::RETRYABLE_A2A_EXCEPTIONS`).
`Settings.multi_agent_max_retries` (default `1`) bounds the retry loop —
never unbounded, and `AgentResult.retry_count` records exactly how many
retries were actually used (not assumed from the configured maximum), so
observability reflects what happened, not what was configured.

### Timeouts

Two independent budgets: `Settings.multi_agent_agent_timeout_seconds`
(default `20.0`) bounds **one specialist's call, including its own
retries** — enforced inside each adapter via `asyncio.wait_for` around
the `A2AClient.submit_task` call; `Settings.multi_agent_timeout_seconds`
(default `45.0`) bounds **the whole workflow** — enforced as a single
coarse `asyncio.wait_for` around `_execute()` in the orchestrator. The
per-call budget is the primary defense (it fires first, in the common
case); the workflow-level one is a last-resort backstop expected to fire
only in a pathological scenario (e.g. a bug that bypasses the per-call
timeout). See "Cancellation" below for the trade-off this implies.

### Loop/delegation-limit prevention

`Settings.max_agent_delegations` (default `5`) caps the total number of
distinct agents one workflow may call; `Settings.max_agent_depth`
(default `2`) caps how deep a delegation chain may go (Orchestrator ->
specialist = depth 1; specialist -> Analyst = depth 2). Both are checked
**before** any agent call is made (`MultiAgentOrchestrator._execute`),
raising `DelegationLimitExceededError`/`WorkflowDepthExceededError`
rather than letting a call happen and failing after the fact. In this
milestone's actual topology neither limit can be reached by a real
request (at most 3 agents, depth 2) — they exist as **defense in depth**
for a future extension where a specialist might delegate further on its
own (see "Future scaling considerations"), and are directly exercised by
`tests/unit/multi_agent/test_retry_and_limits.py` via an artificially
large routing decision.
`app/multi_agent/policies.py::ALLOWED_TRANSITIONS` is the explicit
workflow-transition policy (`orchestrator -> {research, document,
analyst}`, `research -> {analyst}`, `document -> {analyst}`,
`analyst -> {}`) — `Analyst -> Research` (or any other transition not
listed) is structurally impossible, not merely undocumented.

### Correlation IDs

Every workflow gets a `workflow_id` and `correlation_id` (both generated
once, at the top of `MultiAgentOrchestrator.run`) plus a `task_id` per
specialist call (`app/multi_agent/adapters.py::new_task_id`). These are
threaded through every `AgentContext` and every `multi_agent.*`/
`a2a.*` log event for that run — the full trace (routing decision, each
agent's start/completion/failure, retries, final aggregation) is
reconstructable from `correlation_id` alone, without needing separate
unrelated ids per internal step.

### Observability

Structured `structlog` events, safe metadata only (agent/capability
names, durations, statuses, retry counts — never tool arguments, raw
retrieved content, or chain-of-thought):
`multi_agent.workflow_started`, `multi_agent.routing_decision`,
`multi_agent.agent_started`, `multi_agent.agent_completed`/
`agent_failed`, `multi_agent.agent_retry`, `multi_agent.parallel_started`/
`parallel_completed`, `multi_agent.workflow_completed`/`workflow_failed`.
(`multi_agent.aggregation_started` was considered but not added as its
own event: aggregation in this milestone is a single, synchronous,
sub-millisecond function call with no failure mode of its own to observe
separately from `workflow_completed` — adding a distinct event for it
would be exactly the kind of unnecessary observability surface the
brief's "do not over-engineer" section warns against; revisit if
aggregation ever gains its own LLM call or failure mode.)

### Token/cost tracking

`ResearchResult`/`AnalystAgentResult` both gained a `token_usage: dict |
None` field, populated from the real `CompletionResponse.usage
.model_dump()` whenever an LLM call was actually made (`None` when it
wasn't — the Research Agent's no-evidence short-circuit, or the Analyst's
calculation-only path — never a fabricated zero). This travels over the
wire inside each agent's own A2A artifact payload, is coerced back from
the protobuf `Value` wire format's float-only numbers to `int` on the
client side (the same `page_number` round-trip fix from Milestone 7,
applied here to token counts), and `MultiAgentOrchestrator`'s
`_aggregate_token_usage` sums whatever was reported across however many
agents actually called an LLM — reporting an **empty dict** (not a
fabricated total) when no agent in the workflow made an LLM call at all
(e.g. a pure calculation-only or pure document-metadata request). No cost
figure is computed or claimed anywhere — Groq's API does not expose
per-call cost, so only token counts are tracked, consistent with "if the
provider doesn't expose reliable cost data, record usage and leave cost
unavailable."

### Aggregation

`ResultAggregator.combine` (`app/multi_agent/aggregation.py`) takes no
LLM call of its own: when the Analyst ran, its answer already **is** the
cross-agent synthesis (that's precisely the Analyst's job); when it
didn't, there is at most one successful specialist, so there is nothing
left to synthesize — surfacing that one answer directly is simpler and
more honest than an extra LLM call that would just restate it. Failures
are never silently discarded: `combine` always classifies agent_results
into successes/failures first, and a non-empty failures list is appended
to the final answer as an explicit note, never hidden.

### Partial results

`status: "partial"` (set by `ResultAggregator`) is a distinct workflow
status from `"completed"`/`"failed"`/`"timeout"` — a caller can tell the
difference between "everything the workflow needed succeeded" and "some
of it did, here's what's missing" without parsing free text.

### Security

- **No arbitrary agent/MCP endpoint from user input anywhere**:
  `MultiAgentRunRequest` (the only input this milestone's new endpoint
  accepts) has exactly one field, `message` — there is no URL/endpoint
  parameter at any layer a caller could use to redirect the orchestrator.
  `TRUSTED_A2A_AGENTS` (Milestone 7, unchanged) remains the only source of
  truth for which base URL is ever contacted.
- **`delegate`-style redirection is structurally impossible**: the
  Analyst's own argument schema (`expressions`/`evidence`/`question`) has
  no endpoint field either (carried over from Milestone 7's
  `delegate_to_research_agent` guarantee, verified again here:
  `tests/unit/multi_agent/test_orchestrator.py::
  test_untrusted_base_url_is_never_reachable_from_user_input`).
  Capability authorization is double-checked (static policy + the
  target's own discovered Card) before every call — see "Agent capability
  model" above.
  - Retrieved/remote content is always untrusted data: the Analyst's
  system prompt treats `evidence` exactly the way `ResearchAgentService`'s
  own prompt already treats retrieved context (Milestone 7) — verified by
  `test_malicious_retrieved_content_never_reaches_the_system_message` and
  the Analyst's own
  `test_evidence_is_treated_as_untrusted_data_not_instructions`.

### Future scaling considerations

If a fourth specialized agent, or agent-to-agent delegation beyond the
Analyst, were ever added: `CAPABILITY_REGISTRY` gains another `AgentSpec`
entry; `ALLOWED_TRANSITIONS` gains the new edges explicitly (never
implicitly); `max_agent_depth`/`max_agent_delegations` — already enforced
today even though unreachable by this milestone's own topology — would
start actually constraining real requests rather than existing purely as
defense in depth. None of that is built speculatively here; this
milestone adds exactly the three agents and the transitions the brief
asks for.

## How AegisAI implements multi-agent orchestration (for explaining this milestone)

- **MCP** (Milestone 7) is the boundary AegisAI uses when a request needs
  a *capability* — a tool call or a resource read. It standardizes tool
  discovery/invocation, not reasoning.
- **A2A** (Milestone 7) is the boundary AegisAI uses when the work
  belongs to a genuinely different *agent* — a separate reasoning loop
  with its own scope, system prompt, and tool set.
- **Multi-agent orchestration** (this milestone) is what AegisAI builds
  *on top of* A2A when a single request needs more than one agent's
  capability: an orchestrator routes the request, delegates to each
  needed specialist purely through the A2A boundary (never by importing
  its implementation), and aggregates their structured results into one
  answer.
- **Why not one giant agent?** Because a single agent's tool-calling loop
  shares one system prompt, one context budget, and one trust boundary
  across every capability it holds. Splitting research/document/
  calculation into separate A2A agents means each can be scoped, tested,
  and evolved independently — the same reasoning that motivates service
  boundaries, applied to agent capability boundaries instead.
- **Why specialized agents instead of a bigger tool registry?** A tool is
  a single deterministic (or single-LLM-call) action inside one agent's
  loop. A specialist is a *whole reasoning process* with its own prompt
  and scope (e.g. the Analyst's own system prompt, treating supplied
  evidence as untrusted data). When the work is "one more branch in an
  existing loop," it's a tool (see ADR 009, MCP); when it benefits from
  being a separately-scoped reasoning process, it's an A2A agent.
- **Sequential vs. parallel**: independent specialists (Research,
  Document) run in parallel — nothing one needs depends on the other's
  output. A synthesis/calculation step (Analyst) that *consumes* other
  specialists' answers runs sequentially, after they complete — you
  cannot synthesize evidence that doesn't exist yet.
- **Preventing infinite delegation**: a static transition policy
  (`orchestrator -> {research, document, analyst}`, `research/document ->
  {analyst}`, `analyst -> {}`) makes a delegation cycle structurally
  unrepresentable, backed by numeric `max_agent_depth`/
  `max_agent_delegations` ceilings checked before any call is made.
- **Handling partial failure**: every specialist call is normalized into
  a structured `AgentResult` that never raises; the aggregator always
  reports which specialists succeeded and which didn't (`status:
  "partial"`), and never fabricates an answer for one that failed.
- **Securing remote agents**: the same Milestone 7 trusted-agent allowlist
  (`TRUSTED_A2A_AGENTS`) plus independent Agent Card validation — this
  milestone adds zero new ways to reach an untrusted endpoint; the new
  endpoint (`POST /api/v1/multi-agent/run`) accepts only a `message`
  string, with no endpoint/URL field anywhere in the request.

## Testing

- **Routing** (`tests/unit/multi_agent/test_router.py`): all 7 brief
  scenarios plus the UUID/arithmetic collision regression.
- **Capabilities/policy**
  (`tests/unit/multi_agent/test_capabilities_and_policies.py`): capability
  -> agent mapping, allowed/disallowed transitions, the retryable-
  exception allowlist.
- **Aggregation** (`tests/unit/multi_agent/test_aggregation.py`):
  single-success, Analyst-synthesis, partial-failure, total-failure.
- **Document/Analyst agent services**
  (`tests/unit/a2a/test_document_agent_service.py`,
  `test_analyst_agent_service.py`): found/missing documents, safe-field-
  only output, deterministic calculation-only (no LLM call), evidence-
  grounded synthesis, evidence-as-untrusted-data.
- **Orchestrator integration**
  (`tests/unit/multi_agent/test_orchestrator.py`): driven through the
  real `POST /api/v1/multi-agent/run` endpoint against the real Research/
  Document/Analyst endpoints (via `httpx.ASGITransport`, no real socket) —
  direct response, calculation-only, research-only (with/without
  evidence), document-only, the two multi-agent combination examples from
  the brief, document-not-found, partial failure, timeout, the untrusted-
  endpoint structural guarantee, malicious content, and observability
  event coverage.
- **Retry/limits** (`tests/unit/multi_agent/test_retry_and_limits.py`):
  retry success, retry exhaustion, non-retryable failures are never
  retried, delegation-limit/depth-limit enforcement, the overall workflow
  timeout backstop — exercised directly against the orchestrator with the
  adapter layer patched, for fast, deterministic control over failure
  timing.
- **Live** (`tests/integration/test_multi_agent_live.py`, opt-in via
  `RUN_MULTI_AGENT_LIVE_INTEGRATION`, with an additional tier requiring
  `GROQ_API_KEY`): a real `uvicorn` server on a real TCP socket, driving
  the full Research + Document + Analyst workflow end-to-end.
- All M0–M7 tests continue to pass unchanged.

## Consequences

- **Positive**: every specialist call normalizes into the same
  `AgentResult`, so the orchestrator/aggregator logic is completely
  agent-agnostic — adding a fourth specialist later would not change
  `orchestrator.py`'s dispatch logic, only `capabilities.py`/
  `policies.py`/`adapters.py`.
- **Positive**: the deterministic router makes the entire routing policy
  unit-testable in milliseconds, with no flaky/non-deterministic model
  call anywhere in the default test suite.
- **Positive**: real testing (not a loose mock) against the full A2A/HTTP
  stack caught two genuine bugs before they could reach a user-visible
  path — the UUID/arithmetic routing collision, and
  `parse_research_result` never reading back the `token_usage` field a
  payload now carries — both fixed with a one-line change each, found only
  because the tests exercised the real wire round trip.
- **Negative**: the workflow-level timeout backstop cancels the entire
  `_execute()` coroutine, including any tier-1 results already gathered —
  acceptable today because per-call timeouts are tight and this backstop
  is expected to fire only in a pathological case, but a future milestone
  wanting to *always* preserve whatever completed before a late timeout
  would need `asyncio.wait`-based partial-cancellation instead of
  `asyncio.wait_for` around the whole tier.
- **Negative**: `max_agent_depth`/`max_agent_delegations` are unreachable
  by any real request in this milestone's own topology (at most 3 agents,
  depth 2) — correct defense in depth, but their enforcement is only
  exercised today via an artificially constructed routing decision in
  tests, not a real user request; this is explicitly noted, not hidden.
- **Negative**: the Analyst Agent's deterministic calculation-only path
  and its LLM-backed synthesis path are two different code paths inside
  one service — simpler to reason about today (no LLM call needed for
  "what is 15% of 500"), but would need revisiting if a future capability
  needed calculation *and* synthesis to share more logic than they do now.

## Related

- [009-mcp-a2a-architecture.md](009-mcp-a2a-architecture.md) (the A2A
  boundary, Agent Card pattern, and trusted-agent allowlist this milestone
  extends to two more agents rather than replacing)
- [008-agent-architecture.md](008-agent-architecture.md) (`ToolRegistry`/
  `CALCULATOR_TOOL`, reused directly by the Analyst Agent; the "agentic
  RAG, not `RAGService`" precedent `ResearchAgentService` already follows
  and this milestone's `DocumentAgentService`/`AnalystAgentService` follow
  for the same reasons)
- [007-rag-pipeline.md](007-rag-pipeline.md) (`RetrievalService`, reused
  by the Research Agent; the "evidence metadata, not a fabricated
  confidence score" precedent this milestone's agents all follow)
