"""Single-agent LangGraph orchestration with controlled tool calling.

`AgentService` (service.py) -> the compiled `StateGraph` (graph.py) ->
`ToolRegistry` (tools/base.py) -> registered tools: three internal
(tools/calculator.py, tools/document_metadata.py, tools/knowledge_base.py),
MCP-discovered (tools/registry.py, via `app.mcp.client`), and the A2A
Research Agent delegation tool (tools/research_delegation.py, via
`app.a2a.client`). Implemented in Milestone 6 — see
docs/architecture/decisions/008-agent-architecture.md — and extended in
Milestone 7 with MCP and A2A capabilities — see
docs/architecture/decisions/009-mcp-a2a-architecture.md. Still a single
orchestrator with one remote Research Agent, not a multi-agent swarm.
"""
