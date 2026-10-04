# 8. Agentic AI: LangGraph Orchestration, Tool Calling, and Safety Boundaries

## Status

Accepted — 2026-10-04

## Context

Milestone 6 builds the first agentic layer on top of the existing LLM
gateway (Milestone 1), conversation persistence (Milestone 2), and RAG
retrieval (Milestone 5): a single, LangGraph-orchestrated agent that can
decide — per request — whether to answer directly or call one of three
explicitly registered tools (knowledge-base search, a calculator,
document metadata lookup), execute it, observe the result, and decide
again, until it has a final answer or hits a safety limit. It explicitly
does **not** implement MCP, A2A, multi-agent orchestration, external
enterprise integrations, unrestricted computer-use, or any tool capable of
arbitrary Python/SQL/shell execution or unrestricted HTTP. This is
single-agent orchestration with a small, closed set of controlled tools —
not an autonomous agent platform.

## Decision

### Architecture

```
User
 │
 ▼
POST /api/v1/agents/run[/stream]  (api/v1/agents.py)
 │
 ▼
AgentService (app/agents/service.py)
 │  resolve/create conversation, load history, build initial state,
 │  invoke the graph (bounded by a wall-clock timeout), persist the
 │  final turn, extract sources/tool-usage for the API response
 ▼
LangGraph StateGraph (app/agents/graph.py)
 │
 │        ┌─────────────────────────────────────────┐
 │        │                                         │
 ▼        │                                         │
START → agent ──should_continue?── tool calls, under limits ──► tools ──┘
           │
           ├── no tool calls ───────────────► END (final answer)
           ├── over AGENT_MAX_STEPS ────────► max_steps (stop) ──► END
           └── over AGENT_MAX_TOOL_CALLS ───► max_tool_calls (stop) ──► END
```

`agent_node` only ever calls `LLMGateway.chat_completion(..., tools=...)`
and appends the result as a message — it never executes a tool itself.
`tool_node` is the only code that calls `ToolRegistry.execute` — the
brief's "the LLM must never execute tools directly" is structural here,
not a convention: there is no code path from a model's text output to a
Python callable except through this one node, which only accepts
arguments that have already passed JSON-schema validation (see "Tool
schema validation" below).

### LangGraph version and API

`langgraph==1.2.12` (pulling in `langchain-core==1.6.6` as a direct
dependency — LangGraph's state/message model is built on it even when no
LangChain chat model is used, see "Why LLMGateway, not a LangChain chat
model" below). Verified against the **installed** package via direct
introspection (`inspect.signature`, reading `_Node`'s `Protocol`
definition in `langgraph.graph._node`), not assumed from training-data
memory — the brief explicitly required this. Confirmed empirically before
writing any graph code:

- `StateGraph(state_schema)`, `add_node`, `add_edge`,
  `add_conditional_edges(source, path, path_map)`, `.compile()` — all used
  exactly as introspected.
- `astream(..., stream_mode="updates")` yields `{node_name: partial_state}`
  per completed node — confirmed with a minimal throwaway graph before
  relying on it for the streaming endpoint.
- `GraphRecursionError` (from `langgraph.errors`) is the library's own
  infinite-loop backstop, used here as a secondary safety net behind this
  project's own step/tool-call counters (see "Maximum steps" below).

### Why `LLMGateway`, not a LangChain chat model

LangGraph's tool-calling examples typically pair it with a LangChain chat
model (e.g. `ChatGroq`, via `.bind_tools()`), returning LangChain
`AIMessage`s directly from the model call. This project does the
opposite: `agent_node` calls the **existing** `LLMGateway.chat_completion`
(extended with a new optional `tools` parameter — see below), not a
LangChain chat model, and a small boundary module
(`app/agents/messages.py`) translates between LangGraph's message world
(`langchain_core.messages`) and this project's own `app.llm.schemas
.ChatMessage`. This was a deliberate choice, not an oversight: the brief's
engineering rules require reusing `LLMGateway` (its retry policy, typed
error hierarchy, and secret-free logging all already exist and are
tested) rather than introducing a second, parallel LLM call path through
`langchain-groq`. The only new dependency is `langgraph` itself (and its
own `langchain-core` dependency, for message/graph types) — no
`langchain-groq`, no LangChain chat model.

`LLMProvider.complete()` and `CompletionResponse` gained new optional
fields for this milestone: `tools: list[ToolSpec] | None` (request) and
`tool_calls: list[ToolCall] | None` (response) — both default to `None`,
so every existing call site (`ChatService`, `RAGService`) is unaffected.
`GroqProvider` serializes `ToolSpec` into Groq's (OpenAI-compatible)
`tools` parameter and parses `tool_calls` back out of the response,
verified against the actually-installed `groq==1.7.0` SDK's own type
definitions (`ChatCompletionToolParam`, `ChatCompletionMessageToolCall`)
via direct introspection, the same verification discipline as the
LangGraph API above. `stream_complete` was **not** extended with `tools`
— see "Streaming" below for why.

### Agent state: workflow state, not a conversation duplicate

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    step_count: int
    tool_call_count: int
    tool_calls_by_name: dict[str, int]
    status: str
```

This is LangGraph's state schema for the duration of one run only. It is
deliberately **not**, and must never become, a second copy of the
persisted `Conversation`/`Message` domain models:
`AgentService.run`/`run_stream` read prior history from
`MessageRepository` once at the start of a run (mapped into
`HumanMessage`/`AIMessage` via `app.agents.messages
.history_to_langchain_messages`) and persist only the user's question and
the final assistant answer at the end — the same conversation-persistence
boundary `ChatService`/`RAGService` already use. Everything that happens
in between — every intermediate `AIMessage` requesting a tool, every
`ToolMessage` carrying a result — lives only in `AgentState` for the
duration of the run and is **never** written to conversation history.
`MessageRole` (the persisted enum) has no `TOOL` value at all, which is
itself a structural guarantee that tool traffic can't leak into
persisted history by accident.

### Tool abstraction and registry

```
Agent
  │
  ▼
ToolRegistry (app/agents/tools/base.py)
  │  only a name registered here can ever execute
  ▼
ToolDefinition
  │  name, description, args_schema (a Pydantic model), executor,
  │  requires_approval (HITL foundation — see below)
  ▼
Validated execution
```

Each registered `ToolDefinition.to_spec()` derives a provider-neutral
`ToolSpec` (name/description/JSON-schema-from-`args_schema
.model_json_schema()`) — the LLM only ever sees this derived schema, never
hand-written prose duplicating it (avoiding the two drifting apart as a
tool's arguments change). `ToolRegistry.to_tool_specs()` is what's passed
as `LLMGateway.chat_completion(..., tools=...)`.

### Tool schema validation and the result contract

```
LLM-generated arguments (a raw JSON string — untrusted input)
      │
      ▼
json.loads                          -> malformed JSON: ToolResult(error_code="validation_error")
      │
      ▼
args_schema.model_validate           -> schema violation: ToolResult(error_code="validation_error")
      │
      ▼
executor(validated_args)             -> business/authorization checks live here
      │                                 (e.g. "does this document exist" -> "not_found")
      ▼
ToolResult(success, data, error, error_code)
```

`ToolRegistry.execute` **never raises** — an unexpected exception inside a
tool's `executor` is caught, logged via `logger.exception` (server-side
only), and converted into `ToolResult(success=False, error_code=
"internal_error")`, with a generic message the model sees and the real
exception text staying out of it. This is the "Invalid arguments must
produce a controlled tool error... do not crash the entire agent process"
requirement, implemented as the registry's own invariant rather than
something each tool has to remember to do.

### The three tools

- **`search_knowledge_base`** (agentic RAG) wraps
  `app.rag.retrieval.service.RetrievalService` directly — the exact same
  retrieval infrastructure Milestone 5's `RAGService` uses. It does not
  re-implement vector search, re-embed anything, or touch pgvector itself.
  See "Agentic RAG" below for why it does *not* also reuse
  `ContextAssembler`/`RAGPromptBuilder`.
- **`calculator`** parses its `expression` argument with Python's `ast`
  module (`ast.parse(expression, mode="eval")`) and walks the resulting
  tree itself, recognizing only `Add`/`Sub`/`Mult`/`Div`/`FloorDiv`/
  `Mod`/`Pow` (binary) and `UAdd`/`USub` (unary) operators plus numeric
  (`int`/`float`, explicitly not `bool`) literals — **never `eval()` or
  `exec()`**. Anything else (a name, an attribute, a call, a
  comprehension, a string, a lambda) raises `UnsupportedExpressionError`
  before any evaluation happens. Two additional, deliberate bounds prevent
  a *computational* denial-of-service even though code injection is
  already impossible: operand magnitude is capped at `1e9` and the
  exponent of `**` at `100` — a "legitimate" expression like
  `99999 ** 99999` is rejected as a validation error rather than hanging
  the process or exhausting memory. Verified by a dedicated test that
  monkeypatches `builtins.eval`/`builtins.exec` to raise if ever called,
  not just by checking outputs.
- **`get_document_metadata`** reuses `DocumentRepository.get()` directly
  (no new query). Returns only the fields Milestone 3's own
  `DocumentResponse` already treats as safe to expose — filename
  (`original_filename`, never the internal storage key), type, status,
  page/character counts, timestamps, and the extraction `metadata` blob —
  never the checksum, never a filesystem path, never raw embeddings,
  never anything that could leak database/connection configuration.

### Security boundaries

The brief's mandatory list — "the agent must NOT have access to arbitrary
Python, eval, exec, shell, filesystem write, arbitrary SQL, or arbitrary
HTTP requests" — is enforced structurally, not by policy:

- The tool registry is a plain `dict[str, ToolDefinition]` populated by
  exactly one function (`build_tool_registry`), called with exactly three
  `register()` calls. There is no `getattr`/`globals()`/dynamic-import
  path from a tool name string to an arbitrary callable — an unregistered
  name is a `ToolResult(error_code="not_found")`, proven by a test that
  tries names like `"eval"`, `"os.system"`, and `"subprocess.run"`
  against the real registry.
- The calculator never calls `eval`/`exec` (see above) and has no
  filesystem, network, or subprocess access — it's pure arithmetic on an
  AST.
- `get_document_metadata` and `search_knowledge_base` only ever call
  existing repository/service methods (`DocumentRepository.get`,
  `RetrievalService.retrieve`) — neither tool module contains a raw
  `session.execute`/SQLAlchemy `text()` call, an HTTP client call, or
  filesystem access; verified by a source-inspection test, not just
  behavioral tests.
- No tool performs a write. All three are read-only/side-effect-free by
  construction, which is also why none of them need
  `requires_approval=True` in this milestone (see "Human-in-the-loop
  foundation" below).

### Maximum steps, maximum tool calls, and timeout

Three independent, configurable safety limits (`AGENT_MAX_STEPS=8`,
`AGENT_MAX_TOOL_CALLS=10`, `AGENT_TIMEOUT_SECONDS=60.0` — conservative
development defaults, explicitly not production-tuned claims, per the
brief):

- **`AGENT_MAX_STEPS`** bounds the number of `agent` node executions (LLM
  turns) in one run. `should_continue` checks `step_count >=
  agent_max_steps` *before* routing to `tools` — the limit stops the
  *next* LLM-requested tool call from happening, not the one already in
  flight.
- **`AGENT_MAX_TOOL_CALLS`** bounds total tool invocations across the
  whole run, independent of step count (one step can request several
  tool calls at once — `should_continue` checks `tool_call_count +
  requested > agent_max_tool_calls` so a single over-large batch of
  requested calls is rejected as a whole, never partially executed).
- **`AGENT_TIMEOUT_SECONDS`** wraps the *entire* graph invocation
  (`asyncio.wait_for(self._graph.ainvoke(...), timeout=...)`) — a
  wall-clock backstop independent of step/tool-call counting, covering
  the case where a single LLM or tool call itself hangs.

Both counters are checked **before** acting, not after, so exceeding a
limit never means "one more tool call slips through" — the graph routes
to a dedicated `max_steps`/`max_tool_calls` stop node instead, which
appends a fixed, honest message (never a fabricated answer) and sets
`AgentState.status` accordingly. This is a controlled, in-band
`AgentRunResult` outcome (`status: "max_steps_exceeded"` /
`"max_tool_calls_exceeded"`, HTTP `200`) — **not** an error — the same
"the system worked correctly by stopping itself" reasoning
[ADR 007](007-rag-pipeline.md) applies to RAG's "no context" outcome.

A timeout is different: it means the run did **not** complete within its
budget at all, so `AgentTimeoutError` propagates to a registered handler
(`app.core.exceptions`) mapped to HTTP `504` — the same status
`LLMTimeoutError` already uses, for the same reason (a genuine failure to
complete, not a safe self-stop).

`GraphRecursionError` (LangGraph's own recursion-limit exception, config
`recursion_limit = agent_max_steps * 2 + 10`) is caught as a pure backstop
that should never normally trigger, since `should_continue` already stops
the graph before LangGraph's own limit could be reached — it exists only
to convert a future bug in the counting logic above into the same
controlled stop response rather than an unhandled crash.

### Retry policy

Tool failures are **not** retried automatically by the application —
`ToolRegistry.execute` returns a structured `ToolResult` either way, and
the decision to retry (by calling the same tool again with different
arguments, trying a different tool, or giving up and answering honestly)
is left to the model, which sees the failure as a normal observation
(a `ToolMessage` with `success: false`) and can act on it within its own
remaining step/tool-call budget. This mirrors how `LLMGateway` already
classifies failures (`LLMRateLimitError`/`LLMTimeoutError`/
`LLMProviderUnavailableError` are retried there, automatically, since
those really are transient and retry-safe); building a second, tool-level
retry framework on top — distinguishing "transient" from "permanent" tool
failures and retrying only the former — was considered and rejected as
unnecessary complexity for three read-only tools whose only realistic
failure modes are validation errors (permanent — retrying the identical
arguments helps nothing) and "not found" (permanent). `LLMGateway`'s own
retry policy (unchanged by this milestone) still applies to the
underlying provider call every `agent_node` step makes.

### Execution tracing and observability

Structured log events (`agent.started`, `agent.step`, `agent.tool_call`,
`agent.tool_result` via the same `agent.tool_call` event's `success`
field, `agent.completed`, `agent.failed`, `agent.limit_reached`) carry:
run id, conversation id, step/tool-call counts, tool names, per-tool-call
duration and success/error-code, final status, and total duration —
**never** a tool's raw arguments or result content, a full prompt, a full
model response, or an embedding vector, matching every prior milestone's
logging discipline. The correlation id from `CorrelationIdMiddleware`
(bound into structlog's contextvars) threads through automatically, so
every log line from one HTTP request — across the gateway, the graph,
and each tool call — carries the same `request_id`.

### Human-in-the-loop foundation (not implemented)

`ToolDefinition.requires_approval: bool = False` exists as a declared,
inert field in this milestone — all three tools are read-only and
side-effect-free, so none set it `True`. The intended future design: a
graph node checking `requires_approval` on a requested tool call would
route to an `awaiting_approval` state instead of `tools` directly
(LangGraph supports pausing a compiled graph with a checkpointer and
resuming it later via `interrupt_before`/a dedicated interrupt node — not
wired up here, since no sensitive tool exists yet to justify it). The API
would need a way to surface "this run is paused pending approval" and a
separate endpoint to approve/deny and resume — deliberately out of scope
until a tool that actually mutates state (e.g. "submit an expense report")
exists.

### Agentic RAG: a second caller of `RetrievalService`, not a duplicate

```
Agent
  │
  ▼
search_knowledge_base
  │
  ▼
RetrievalService.retrieve  (same call RAGService makes)
  │
  ▼
pgvector
  │
  ▼
results -> ToolResult(data={"results": [...]})
  │
  ▼
Agent  (sees the results as data, decides whether another tool call is needed)
```

The tool deliberately does **not** reuse `ContextAssembler` or
`RAGPromptBuilder`: those produce a rendered RAG *prompt* (`[SOURCE n]`
blocks, `[S1]`-style citation framing) meant to be the final user turn of
a single-shot RAG call. A tool result is different — it's one observation
in an ongoing agent loop that the model will keep reasoning over, possibly
alongside a calculator result in the same answer. Forcing it through
`ContextAssembler` would impose RAG-specific formatting and a citation
contract the agent system prompt doesn't establish. Instead, the tool
returns a plain structured list (`chunk_id`, `document_id`, `filename`,
`page_number`, `similarity`, `content`) that `AgentService` separately
maps into `AgentSource` for the API response — transparency about what
was consulted, without inheriting RAG's inline-citation design.

### Conversation integration and memory strategy

`AgentService` reuses `ConversationRepository`/`MessageRepository`
directly — the same repositories `ChatService`/`RAGService` use, no new
conversation storage. The initial memory strategy is explicit, not
sophisticated: the **full** prior history is loaded and included, in
order, exactly as `PromptBuilder`/`RAGPromptBuilder` already do — no
truncation, no summarization, no token-budget enforcement. This is a
known, existing limitation already documented for RAG in
[ADR 007](007-rag-pipeline.md), inherited here rather than newly
introduced; fixing it (a message-count or token-budget cutoff) is
deferred, same reasoning as ADR 007's conversation-history stance.

### Streaming: safe events only, never chain-of-thought

`POST /api/v1/agents/run/stream` emits exactly four event types —
`tool_started`, `tool_completed`, `answer_delta`, `completed` — built on
`astream(..., stream_mode="updates")`. Each `agent` node update that
requests tool calls immediately yields a `tool_started` event per
requested call (before execution); each `tools` node update yields
`tool_completed` per result. **No event ever carries an `AIMessage`'s
free-text content before the final answer** — an intermediate assistant
message explaining *why* it's calling a tool is exactly the kind of
reasoning trace the brief says must never be streamed, so only the
structured fact of a tool call (its name) and its outcome (success/failure)
are ever emitted, never the model's own words about either.

The final answer is delivered as a single `answer_delta` event carrying
the complete text, not streamed token-by-token. This is a deliberate
simplification, not an oversight: tool-call decisions need the complete
structured output from the provider (you cannot act on half a JSON tool
call), so the agent loop's internal LLM calls are all non-streaming
(`chat_completion`, not `stream_chat_completion` — which is why `tools`
was added only to `complete()`, not `stream_complete()`). By the time the
graph reaches `END`, the final answer already exists in full; re-issuing
a second, real streaming LLM call purely to animate its delivery would
produce a *different* (non-deterministic) response than the one the graph
actually decided on, which is worse than delivering the real answer as
one chunk.

### Error handling

Mirrors [ADR 007](007-rag-pipeline.md)'s "reuse, don't duplicate"
approach: `app/agents/exceptions.py` defines only `AgentError` (base) and
`AgentTimeoutError`. Query-embedding failures during
`search_knowledge_base` surface as the existing
`EmbeddingProviderError`/`EmbeddingDimensionMismatchError` (already
mapped to 502/500); generation failures as the existing `LLMError`
hierarchy (429/503/504/502/400); an unknown `conversation_id` as the
existing `NotFoundError` (404). Tool-level failures never become
exceptions at all — they're `ToolResult`s the model sees as data, per
the result contract above.

## Consequences

- **Positive**: reusing `LLMGateway` means the agent's underlying provider
  calls get the exact same retry policy, typed error hierarchy, and
  secret-free logging as plain chat and RAG, for free — no parallel LLM
  integration to maintain.
- **Positive**: the tool registry's explicitness (one factory function,
  three `register()` calls, no dynamic dispatch) makes "what can this
  agent actually do" fully auditable by reading one file
  (`app/agents/tools/registry.py`).
- **Positive**: `requires_approval` and the `RetrievalStrategy`-style
  seam this milestone's `ToolDefinition`/`ToolRegistry` establish mean a
  future sensitive tool or a reranking/hybrid-search upgrade to
  `search_knowledge_base` are additive, not an `AgentService` rewrite.
- **Negative**: no conversational memory limit (same as RAG) means a long
  multi-turn conversation grows the prompt unboundedly — documented, not
  hidden, and not newly introduced by this milestone.
- **Negative**: the final answer is never provider-streamed token-by-token
  — an explicit, reasoned simplification (see "Streaming" above), not a
  missing feature, but a real UX difference from the plain chat/RAG
  streaming endpoints.
- **Negative**: tool-level retry is deliberately absent; for three
  read-only tools with no transient-failure modes this is the right
  amount of complexity today, but it would need revisiting before adding
  a tool that calls an external, occasionally-flaky service.

### Evaluation approach

A small, fully deterministic fixture
(`tests/evaluation/agent_fixtures.py` + `test_agent_evaluation.py`, 9
scenarios covering the brief's full list — direct answer, RAG, calculator,
document metadata, multi-step RAG+calculator, tool failure, no relevant
knowledge, malicious tool output, maximum-step protection) runs against
the **real** `AgentService`/graph/tool registry with every LLM response
scripted via `ScriptedAgentGateway`. This is explicitly **not** a
measurement of real-model tool-selection accuracy — scripting every LLM
response makes it a behavioral regression checklist ("does the
application layer handle this scenario the way it's designed to, every
time, deterministically"), not a sampled or statistical claim about what
a real model would choose unprompted. The separate opt-in
`test_agent_live.py` (gated on `GROQ_API_KEY`, same pattern as
`test_groq_live.py`) exercises the real Groq model's actual tool-selection
behavior for two scenarios (calculator, no-tool-needed), validated
structurally (the right tool was called, the computed number appears in
the answer) rather than by exact wording — but two scripted-prompt samples
against one model is not a benchmark and no accuracy percentage is
claimed from it, consistent with the brief's explicit instruction not to
claim "agent accuracy" from a tiny synthetic dataset.

## Related

- [001-modular-monolith.md](001-modular-monolith.md) (the provider-neutral,
  single-import-point pattern `GroqProvider` already established, extended
  here for tool calling rather than duplicated)
- [002-llm-gateway.md](002-llm-gateway.md) (the `LLMGateway` this milestone
  extends with `tools`/`tool_calls` rather than bypassing)
- [004-conversation-persistence.md](004-conversation-persistence.md) (the
  atomicity pattern `AgentService` mirrors)
- [007-rag-pipeline.md](007-rag-pipeline.md) (`RetrievalService`, reused
  directly by the `search_knowledge_base` tool; the "no-context"/"no
  conversational memory limit" precedents this milestone's `max_steps`
  outcome and memory strategy both follow)
