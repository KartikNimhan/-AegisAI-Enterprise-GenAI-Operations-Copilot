# 9. MCP and A2A Interoperability: Standardized Tool and Agent Boundaries

## Status

Accepted — 2026-10-04

## Context

Milestone 6 gave the agent three internal tools and a bounded LangGraph
loop. Milestone 7's goal is narrow and deliberately small: demonstrate
**two different interoperability protocols** — MCP (Model Context
Protocol, a standardized boundary for exposing *tools/resources* to an
agent) and A2A (Agent2Agent, a standardized boundary for one agent to
delegate work to *another agent*) — as a clear, interview-explainable
reference implementation, not a production multi-agent platform.

Explicitly out of scope: a multi-agent swarm, an autonomous agent
society, an enterprise agent registry, arbitrary MCP tool execution,
arbitrary remote code execution, unrestricted network access, a
distributed task queue, Kubernetes, or a service mesh. This milestone
adds exactly one MCP server (wrapping the three existing internal tools)
and exactly one remote agent (a Research Agent), reached through the real
protocol boundaries rather than by calling their implementation code
directly.

## Decision

### MCP vs A2A — the architectural distinction this milestone demonstrates

- **MCP** standardizes the boundary between an agent and a **capability**
  (a tool call or a resource read). The agent is still the same single
  orchestrator; MCP only changes *how* a tool's schema is discovered and
  *how* the call is transported, not who is doing the reasoning.
- **A2A** standardizes the boundary between **two independent agents**.
  The Research Agent has its own reasoning loop (retrieve → synthesize)
  running in a separately addressable "agent" identity (an Agent Card, a
  task lifecycle) — the orchestrator never imports or calls
  `ResearchAgentService` directly; it only ever goes through
  `A2AClient`.

Both internal tools and MCP-discovered tools end up as the exact same
`app.agents.tools.base.ToolDefinition` the M6 `ToolRegistry` already
understood — the graph/registry code needed **zero changes** to support
MCP, which is itself evidence the two protocols solve different problems:
MCP is absorbed at the tool-registration boundary, while A2A needed a new
kind of capability (`delegate_to_research_agent`) because it is reaching
a different reasoning process, not just a different transport for a tool
call.

### MCP architecture

```
app/mcp/server.py   build_mcp_server(documents, retrieval) -> MCPServer
                     registers calculator / get_document_metadata /
                     search_knowledge_base as MCP tools (thin adapters
                     over the *same* ToolDefinition.executor the internal
                     agent uses — no second implementation) and one
                     resource, document://{document_id}

app/mcp/client.py   discover_mcp_tool_definitions(server, settings)
                     -> list[ToolDefinition]
                     discovers tools from the server (not hardcoded),
                     validates each against the server- and tool-level
                     allowlists, wraps each approved one as a
                     ToolDefinition the same ToolRegistry registers
                     (mcp_-prefixed name)

app/agents/tools/registry.py
                     build_tool_registry(...) now async: registers the
                     3 internal tools, the delegate_to_research_agent
                     tool, THEN discovers and registers MCP tools —
                     internal tools always exist even if MCP discovery
                     fails (see "Resilience" below)
```

### MCP SDK and version

`mcp==2.3.0` (the `mcp` PyPI package). Verified directly against the
**installed** package before writing any code — the import path assumed
from general MCP knowledge (`mcp.server.fastmcp.FastMCP`) does not exist
in this version; the SDK's own `ModuleNotFoundError` message pointed at
the real one: `MCPServer` in `mcp.server.mcpserver`. Decorators
(`@server.tool(...)`, `@server.resource(...)`) and the client
(`mcp.client.Client`) were confirmed via `inspect.signature` against the
real classes, not assumed from training-data memory.

### MCP transport

The agent's own calls to the MCP server use **`mcp.client.Client`'s
in-process connect mode** — `Client(server_instance)` — an SDK-documented
transport that talks to an `MCPServer` object directly over an in-memory
stream pair, not a workaround. The MCP server and the agent that calls it
live in the same Python process here; this is a reference implementation
demonstrating the MCP *protocol boundary* (discovery, schema validation,
structured errors), not a deployment topology, so there is no real
network hop to make and no reason to pay for one.

For an **external** MCP client (the MCP Inspector, an IDE's MCP config,
Claude Desktop), `scripts/mcp_stdio_server.py` runs the same
`build_mcp_server(...)` over `server.run_stdio_async()` — the standard
stdio transport a real external client expects, against the real
Postgres-backed `RetrievalService`/`DocumentRepository` (not a demo/fake
server). `tests/integration/test_mcp_stdio_live.py` (opt-in, see
"Testing" below) spawns this script as a real subprocess and talks to it
exactly as an external client would, proving the stdio entrypoint
actually works end-to-end.

### MCP tool discovery

`discover_mcp_tools` calls `client.list_tools()` against the server and
returns what the server actually advertises — tool names, descriptions,
and JSON schemas are never hardcoded on the client side. Each discovered
tool's JSON schema is turned into a **dynamically constructed Pydantic
model** (`_model_from_json_schema`, via `pydantic.create_model`) mapping
JSON Schema scalar/array/object types to Python types (unrecognized types
fall back to `Any` rather than rejecting the whole tool) — arguments are
validated against what the server *actually* said, not an assumption
baked in at write-time.

### MCP tool schema constraint (flat vs nested parameters)

A tool function whose single parameter is a Pydantic model
(`async def calculator(args: CalcArgs) -> dict`) produces a **nested**
JSON schema (`{"properties": {"args": {"$ref": ...}}}`) from the
installed SDK — verified empirically by inspecting a throwaway server's
discovered schema — which does not match the flat schema the LLM/agent
already expects for the internal tool of the same name. Each adapter in
`app/mcp/server.py` therefore takes the same fields as plain,
individually-typed parameters (`async def calculator(expression: str)`),
reconstructs the shared `args_schema` internally, and calls the shared
`executor` — arguments are validated by the *same* Pydantic model either
way, just assembled from flat kwargs instead of a single model argument.
This is a protocol adapter concern, not a second implementation of
calculator/metadata/search logic.

### MCP resources

One resource is implemented: `document://{document_id}`, returning the
exact same safe fields `get_document_metadata`/Milestone 3's own document
API already consider client-facing (filename, type, status, page/char
counts, timestamps) — never a filesystem path, checksum, embedding, or
internal configuration. MCP *prompts* were considered (the installed SDK
does expose `@server.prompt()`) but are not implemented: none of this
milestone's three tools need a templated prompt fragment served over MCP,
and adding one with no real consumer would be exactly the kind of
unnecessary surface the brief says to avoid. This is a documented scope
decision, not a missing feature.

### MCP security

- **Server allowlist**: `Settings.trusted_mcp_servers` (default:
  `["aegisai-internal"]`) — discovery refuses to proceed against any
  server identity not on this list (`MCPServerNotTrustedError`).
- **Tool allowlist**: `Settings.trusted_mcp_tools` (default: the three
  known tool names) — a tool the server advertises but that isn't on this
  list is dropped during discovery (`MCPToolNotTrustedError`), logged,
  and never registered. The server could start advertising a fourth tool
  tomorrow and it would silently never reach the agent without this list
  being updated first.
- **No arbitrary/user-supplied MCP endpoints** anywhere — the server
  instance is always the one this process built; there is no code path
  that accepts an MCP server address from a request, a tool argument, or
  model output.
- **Argument validation on both sides**: the client validates LLM-
  generated arguments against the dynamically-built schema before
  sending them (the same `ToolRegistry.execute` validation path every
  tool goes through); the server independently validates them again when
  reconstructing the real `args_schema` inside each adapter — a
  compromised or buggy client-side schema can't smuggle invalid data past
  the server.

### MCP error categories

Distinguished explicitly, never surfaced as a raw exception:
connection/transport failure and timeout are both caught around the
`async with Client(server)` block (`error_category="connection"` /
`"timeout"` in the `mcp.tool_failed` log event) and become
`ToolResult(success=False, error_code="transient_error")`; a tool
executing but reporting its own failure (`result.is_error`) becomes
`error_code="internal_error"`; discovery failures are their own typed
exceptions (`MCPToolDiscoveryError`, `MCPTimeoutError`,
`MCPServerNotTrustedError`) that the resilient wrapper
(`discover_mcp_tool_definitions`) catches so a broken/unavailable MCP
server degrades to "no MCP tools," never a broken agent.

**A real correctness bug found and fixed while testing this**: cancelling
an in-flight `client.list_tools()`/`client.call_tool()` via
`asyncio.wait_for(..., timeout=...)` *while still inside* `Client`'s
`async with` block causes the client session's internal `anyio`
`TaskGroup` to re-wrap the resulting `CancelledError`/`TimeoutError` as a
`BaseExceptionGroup` during the block's own `__aexit__` — a plain
`except TimeoutError` never matches a `BaseExceptionGroup`, so a genuine
timeout was being silently misreported as a generic connection failure.
Both `discover_mcp_tools` and the per-call executor in `app/mcp/client.py`
use `except* TimeoutError` / `except* Exception` (PEP 654 exception
groups) instead, which correctly unwraps and matches the inner exception
regardless of whether it arrived solo or inside a group. This was caught
by a unit test that forced a real timeout against the real in-process
transport (`tests/unit/mcp/test_mcp_client.py`), not by manual testing —
the exact value of testing against the real library instead of a loose
mock.

### MCP observability

Structured `structlog` events, safe metadata only (tool/server names,
durations, booleans — never arguments or results, which may contain
retrieved document content): `mcp.server_started` (server construction),
`mcp.tool_discovered` (once per approved tool during discovery, plus
`mcp.tool_not_trusted`/`mcp.tool_discovery_failed` for the resilience
path), `mcp.tool_call` (before each invocation), `mcp.tool_completed` /
`mcp.tool_failed` (with `error_category`, `duration_ms`).

### A2A architecture

```
app/a2a/agent_card.py   build_research_agent_card(settings, base_url)
                         -> AgentCard   (a2a.types, real protobuf)
app/a2a/research_agent.py
                         ResearchAgentService.research(question)
                         -> ResearchResult
                         reuses RetrievalService + LLMGateway directly
                         (not RAGService — see "Why not RAGService" below)
app/a2a/tasks.py         build_task(question, result) -> Task
                         task_to_dict(task) -> dict   (a2a.types Task/
                         Artifact/Part, real protobuf, real TaskState)
app/a2a/client.py        A2AClient.fetch_agent_card / submit_research_task
                         the ONLY way the orchestrator reaches the
                         Research Agent — never ResearchAgentService
                         directly
app/agents/tools/research_delegation.py
                         delegate_to_research_agent: a ToolDefinition
                         wrapping A2AClient, registered into the same
                         ToolRegistry as internal/MCP tools
app/api/v1/research_agent.py
                         GET /.well-known/agent-card.json (unversioned)
                         GET /api/v1/agents/research/card (alias)
                         POST /api/v1/agents/research/tasks
```

### A2A SDK and version

`a2a-sdk==1.2.1`. Verified directly: `a2a.types.AgentCard`/`Task`/
`Artifact`/`Part`/`Message`/`TaskStatus` are **protobuf-generated
classes**, not Pydantic models — confirmed by inspecting their MRO and
`DESCRIPTOR` attributes, not assumed. Protocol version **0.3**, confirmed
empirically from the SDK's own default `protocolVersion` field value on a
freshly constructed `AgentCard`, not from documentation that might be
stale relative to the installed version.

### Why a thin HTTP client rather than the full a2a-sdk client/server

The installed SDK ships a full server/client framework: task stores,
queue managers, multi-transport dispatchers (JSON-RPC/gRPC/REST),
interceptors, cluster/database-backed task persistence. That framework is
designed for a production, multi-tenant agent server handling many
concurrent, potentially long-running tasks across transports — it is
**wildly disproportionate** to "one small, synchronous Research Agent"
in a reference implementation, and adopting it would mean pulling in and
configuring infrastructure (a task store, a queue manager) this milestone
explicitly says not to add ("no complex distributed task queues").

Instead: `a2a.types` is used directly for **spec-accurate object
construction** (the real `AgentCard`/`Task`/protobuf types, so the wire
JSON matches what a real A2A client/tool would expect), but the actual
HTTP transport is a thin custom FastAPI router (`app/api/v1/research_agent.py`)
on the server side and a minimal `httpx.AsyncClient` (`app/a2a/client.py`)
on the orchestrator side. This keeps the protocol *shape* correct and
spec-verified while keeping the actual moving parts proportionate to one
agent, one skill, one synchronous call.

### Agent Card

Built from `a2a.types.AgentCard`/`AgentCapabilities`/`AgentSkill`/
`AgentInterface` — fields (`supportedInterfaces`, `protocolBinding`,
`defaultInputModes`/`defaultOutputModes`, `skills`, `capabilities`,
`protocolVersion`, `preferredTransport`) are exactly what the installed
SDK's own `agent_card_to_dict` serializer produces, never invented. One
field name was wrong on the first attempt — `AgentInterface(transport=...)`
raised `Protocol message AgentInterface has no "transport" field`; the
real field, found via `DESCRIPTOR.fields`, is `protocol_binding`. Served
at `/.well-known/agent-card.json` (from `a2a.utils.constants.
AGENT_CARD_WELL_KNOWN_PATH`), the standard A2A discovery convention, kept
unversioned the same way `/health` is.

### A2A task lifecycle

The real `TaskState` enum: `TASK_STATE_SUBMITTED -> TASK_STATE_WORKING ->
TASK_STATE_COMPLETED`, or `TASK_STATE_WORKING -> TASK_STATE_FAILED` —
not an invented set of states. This milestone's Research Agent endpoint
is **synchronous**: it runs the task to completion and returns the final
`Task` (`completed` or `failed`) in one HTTP response. `submitted`/
`working` are logged as transient `a2a.task_started` events rather than
being independently queryable — there is no task store to poll against,
the same simplification Milestone 3 made for its own document-processing
sub-steps. A client only ever observes the terminal state.

### A2A client (orchestrator side)

`A2AClient.submit_research_task(base_url, question=...)`:
`_ensure_trusted(base_url)` → `fetch_agent_card` (validates identity) →
POST to the card's own advertised task URL → parse the `Task` JSON back
into a `ResearchResult`, never trusting the shape blindly (a `completed`
task with no result artifact is treated as a task failure, not a crash).
The orchestrator **discovers** the Research Agent's capability by reading
its Agent Card's `skills` (`RESEARCH_SKILL_ID = "research_question"`) and
its task endpoint from `supportedInterfaces` — not hardcoded — even
though in this reference implementation there is only one remote agent to
discover.

### Trusted-agent model (A2A security)

- `Settings.trusted_a2a_agents` (default: `["http://localhost:8000"]`) —
  an explicit base-URL allowlist. `_ensure_trusted` is checked **before**
  any network call, both in `fetch_agent_card` and
  `submit_research_task` — an untrusted `base_url` never reaches `httpx`.
- The fetched Agent Card is a **second, independent** trust signal: its
  `name` must equal `Settings.research_agent_name` and it must advertise
  the `research_question` skill and at least one supported interface
  before any task is submitted — a URL being allowlisted does not alone
  imply the thing answering at that URL is the expected agent.
- `delegate_to_research_agent`'s own argument schema
  (`ResearchDelegationArgs`) has exactly one field, `question` — there is
  no `url`/`endpoint`/`base_url` parameter the LLM could ever populate.
  The target agent is fixed at tool-construction time from
  `Settings.trusted_a2a_agents[0]`, never from model output; this is a
  structural guarantee, not a runtime check that could be bypassed by a
  cleverly crafted tool call (see `tests/unit/agents/
  test_agent_mcp_a2a_integration.py::test_delegation_tool_schema_exposes_no_endpoint_argument`).
- No user-supplied or runtime-discovered A2A endpoint is ever accepted
  anywhere in this milestone.

### A2A failure handling

`A2AClient` raises distinct typed exceptions —
`A2AUntrustedAgentError`, `A2AInvalidCardError`, `A2AConnectionError`,
`A2ATimeoutError`, `A2ATaskFailedError` — all caught by
`delegate_to_research_agent`'s executor and converted into a structured
`ToolResult(success=False, error_code=...)`, the same contract every
other tool uses; an A2A failure degrades the agent run (the model sees a
clear tool failure and can decide what to do next) rather than crashing
it. `Settings.a2a_client_timeout_seconds` bounds every HTTP call the
client makes — the orchestrator never waits forever on an unresponsive
or hung Research Agent. The Research Agent's own endpoint
(`app/api/v1/research_agent.py`) catches `LLMError` and any unexpected
exception and returns a `failed` `Task` (HTTP 200, structured failure in
the body) rather than fabricating a result or leaking an internal
exception.

### Why `ResearchAgentService` reuses `RetrievalService`/`LLMGateway` directly, not `RAGService`

`RAGService` (Milestone 5) is conversation-scoped: it reads/writes
`Conversation`/`Message` history, has a no-context short-circuit tied to
a persisted turn, and assembles `[SOURCE n]`-style citations into a chat
answer meant for a human reading a chat UI. An A2A task is a single,
stateless request/response with no conversation to persist against —
forcing it through `RAGService` would mean either fabricating a
conversation for every task or stripping out machinery the task doesn't
need. This is the same "lean, task-shaped reuse of the same primitives"
decision Milestone 6 made for `search_knowledge_base` relative to
`RAGService`/`ContextAssembler`/`RAGPromptBuilder` (see ADR 008, "Agentic
RAG") — reused here for the Research Agent's own synthesis step.

### Why M7's A2A task handling is synchronous

No task store, no polling, no message broker. A production A2A deployment
with long-running research tasks would need one; this milestone's
Research Agent does one retrieval call and one LLM call, both already
bounded by existing timeouts, so a synchronous request/response is
simpler and sufficient — adding a task store for a sub-second operation
would be exactly the "complex distributed task queue" the brief says to
avoid.

### Internal tools vs MCP tools vs A2A agents — when to use which

- **Internal tool** (`calculator`, `get_document_metadata`,
  `search_knowledge_base`): the capability's logic and the agent that
  calls it are deployed together; no protocol boundary is needed at all.
  This remains the default, lowest-overhead path for any first-party
  capability.
- **MCP tool**: the same kind of capability, but exposed through a
  standardized tool-discovery/invocation boundary — appropriate when a
  capability might reasonably be consumed by a *different* client someday
  (an IDE, the MCP Inspector, a different internal service) without that
  client needing to know AegisAI's internal Python APIs. This milestone's
  MCP server re-exposes the same three tools specifically to demonstrate
  that boundary, not because a second internal consumer exists yet.
- **A2A agent**: a fundamentally different reasoning process with its own
  scope and its own prompt — appropriate when the work genuinely benefits
  from being a separate "agent" (a different system prompt, a narrower
  tool set, independent evolution/ownership) rather than one more branch
  inside the orchestrator's own tool-calling loop.

### Why M7 has exactly one remote agent (not a multi-agent system)

The brief is explicit that this is a reference implementation meant to be
explainable in an interview, not a production agent platform. One
orchestrator, one Research Agent, reached through a real protocol
boundary, is sufficient to demonstrate: Agent Card-based capability
discovery, the task lifecycle, trust/allowlisting, and failure handling —
every property a larger multi-agent system would also need, just without
the added complexity of agent discovery at scale, load balancing across
agent instances, or cross-agent conversation state, none of which this
milestone's brief asks for.

### Future multi-agent architecture (not built here)

If AegisAI ever needed more remote agents, the seams this milestone
establishes are exactly where that would extend: `Settings.
trusted_a2a_agents` becomes a list of more than one base URL; the
orchestrator's capability discovery (already reading the Agent Card
rather than hardcoding the skill) would pick an agent by matching a
requested skill against multiple cards instead of assuming index `[0]`;
and `delegate_to_research_agent` would become a small family of
delegation tools (or one generic "delegate to agent X" tool parameterized
by a pre-validated agent identifier, never a URL). None of that is needed
today and none of it is built speculatively here.

## How AegisAI uses MCP and A2A (for explaining this milestone)

- **MCP** is the standardized boundary this project uses when a
  *capability* (a tool call, a resource read) might need to be reached by
  more than just this one agent's own Python code — it standardizes tool
  discovery and invocation, not reasoning. AegisAI's MCP server
  re-exposes the same three internal tools over this boundary and the
  agent consumes them through the same `ToolRegistry` abstraction it
  already had, proving the boundary is additive, not a rewrite.
- **A2A** is the standardized boundary this project uses when the work
  belongs to a genuinely different *agent* — a separate reasoning loop
  with its own scope — rather than a capability the orchestrator could
  just call itself. AegisAI's Research Agent demonstrates Agent Card-based
  discovery, a real (if synchronous) task lifecycle, and an explicit
  trust boundary, without claiming the production-scale capabilities
  (multi-tenant task queues, agent registries, cross-transport
  dispatch) that a real enterprise A2A deployment would eventually need
  and that the installed `a2a-sdk` can provide when that day comes.
- Put simply: **MCP answers "how does this agent get a tool," A2A answers
  "how does this agent talk to another agent."** AegisAI implements both
  boundaries correctly and minimally, with exactly the number of servers/
  agents needed to demonstrate each (one MCP server, one remote agent),
  not the infrastructure a production deployment of either protocol would
  eventually need.

## Testing

- **MCP unit** (`tests/unit/mcp/`): server startup/tool listing, each of
  the three tools (success + failure), the document resource (success +
  unknown document), unknown-tool-name handling, the server/tool
  allowlists, discovery success/failure/timeout, and — found via this
  testing, not assumed — the `except*`/`BaseExceptionGroup` timeout fix
  described above.
- **MCP integration** (`tests/integration/test_mcp_stdio_live.py`,
  opt-in via `RUN_MCP_STDIO_INTEGRATION`): spawns the real stdio
  entrypoint as a subprocess against real Postgres.
- **A2A unit** (`tests/unit/a2a/`): Agent Card shape/validation,
  `ResearchAgentService`'s no-evidence short-circuit and evidence-grounded
  path (and that retrieved content never leaks into the system message),
  `Task` construction/serialization for both lifecycle outcomes, and
  `A2AClient`'s allowlist/validation/timeout/connection/task-failure
  paths against a mocked HTTP transport.
- **A2A integration** (`tests/integration/test_a2a_live.py`, opt-in via
  `RUN_A2A_LIVE_INTEGRATION`, with an additional tier requiring
  `GROQ_API_KEY`): runs the real FastAPI app behind a real `uvicorn`
  server on a real TCP socket and drives it with the real `A2AClient` —
  proving the whole wire path (sockets, HTTP, JSON, protobuf
  (de)serialization), not just the application code above it.
- **Agent-level integration**
  (`tests/unit/agents/test_agent_mcp_a2a_integration.py`): the full
  `ToolRegistry` (internal + MCP + the A2A delegation tool) wired into
  the real `AgentService`/graph, covering all 14 scenarios from the
  brief: direct response, internal calculator/RAG, MCP calculator/
  knowledge search, A2A delegation, a multi-step run using an A2A result,
  MCP failure/timeout, A2A failure/timeout, a malicious MCP tool result,
  a malicious A2A result, and the untrusted-endpoint-rejection guarantee
  — all against fakes/mocked transports, no real network or DB.
- All M0–M6 tests continue to pass unchanged; `AgentService`/
  `build_tool_registry` became `async` (to await MCP discovery) but the
  external behavior and contracts Milestone 6 established are otherwise
  untouched.

## Consequences

- **Positive**: MCP tools and internal tools are genuinely
  indistinguishable to the graph/registry — adding MCP required zero
  changes to `app/agents/graph.py`'s dispatch logic (only a new
  observability `capability` label), confirming the `ToolDefinition`
  abstraction from M6 was the right seam.
- **Positive**: the Agent Card + task-lifecycle + allowlist pattern this
  milestone establishes for one remote agent extends cleanly to more
  agents later (see "Future multi-agent architecture") without a rewrite.
- **Positive**: testing against the real MCP SDK's in-process transport
  (rather than a loose mock) surfaced a genuine `except*`/
  `BaseExceptionGroup` timeout-handling bug before it could reach
  production — direct evidence for using real libraries in tests over
  mocks wherever the real thing is cheap enough to run.
- **Negative**: the A2A task handling is synchronous with no task store —
  acceptable for one fast Research Agent today, but would need
  revisiting (a real task store, polling or push notifications) before
  adding a remote agent whose work can take longer than one HTTP
  request's timeout budget.
- **Negative**: `delegate_to_research_agent` always targets
  `trusted_a2a_agents[0]` — correct and safe for exactly one remote
  agent, but would need the capability-matching extension described in
  "Future multi-agent architecture" before a second remote agent is
  added.
- **Negative**: MCP tool execution opens a fresh `Client(server)`
  connection per call rather than reusing one for the agent's lifetime —
  simpler and cheap over the in-process transport used today, but would
  be worth revisiting if a real network transport is ever adopted.

## Related

- [008-agent-architecture.md](008-agent-architecture.md) (the
  `ToolDefinition`/`ToolRegistry`/`AgentService`/graph this milestone
  extends, not rewrites; the "agentic RAG, not `RAGService`" precedent
  `ResearchAgentService` follows for the same reasons)
- [007-rag-pipeline.md](007-rag-pipeline.md) (`RetrievalService`,
  `ContextAssembler` — reused directly by both `search_knowledge_base`
  and `ResearchAgentService`)
- [002-llm-gateway.md](002-llm-gateway.md) (`LLMGateway`, reused directly
  by `ResearchAgentService` for its synthesis step)
