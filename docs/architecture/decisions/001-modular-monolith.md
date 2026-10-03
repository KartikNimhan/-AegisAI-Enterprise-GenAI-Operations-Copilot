# 1. Use a Modular Monolith Architecture

## Status

Accepted — 2026-10-03

## Context

AegisAI's roadmap includes an LLM gateway, RAG, embeddings/vector search,
LangGraph agents, tool calling, MCP, multi-agent workflows (A2A), memory,
evaluation, security/RBAC, observability, async workers, and eventually
Kubernetes deployment. That is a wide surface area to build incrementally,
by a small team, without knowing in advance which subsystems will need to
scale or be deployed independently.

Two common starting points were considered:

- **Microservices from day one**: each capability (LLM gateway, RAG,
  agents, ...) as its own deployable service with its own API contract.
- **Modular monolith**: a single deployable FastAPI application with hard
  internal module boundaries, deployed as one unit.

## Decision

Build AegisAI as a modular monolith. A single `backend/app` codebase is
organized into clearly bounded packages (`api`, `core`, `domain`,
`services`, `llm`, `rag`, `agents`, `tools`, `mcp`, `memory`, `evaluation`,
`observability`, `workers`, `db`), each owning its own concerns. API routes
stay thin and delegate to services; services depend on domain and
infrastructure modules, never the reverse.

## Consequences

- **Positive**: one deployable artifact, one dependency graph, one test
  suite, and one CI pipeline during the early, fast-changing phase of the
  project. Refactors across module boundaries are regular code changes, not
  cross-service API migrations. Local development only requires running
  one process plus Postgres and Redis.
- **Positive**: module boundaries are enforced by code review and import
  discipline now, which is cheap, and can be extracted into separate
  services later if a module's resource profile (e.g., GPU-bound embedding
  workers) genuinely diverges from the rest of the application.
- **Negative**: without discipline, module boundaries can erode over time
  (e.g., a service reaching directly into another module's internals).
  Mitigated by keeping routes thin and reviewing cross-module imports.
- **Negative**: the whole application scales as one unit. Acceptable for
  the current stage; revisit if a specific module (e.g., `workers`) needs
  independent scaling before the rest of the system does.

## Related

- [002-llm-gateway.md](002-llm-gateway.md)
- [003-vector-store.md](003-vector-store.md)
