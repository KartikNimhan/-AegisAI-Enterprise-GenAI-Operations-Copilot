"""Single-agent LangGraph orchestration with controlled tool calling.

`AgentService` (service.py) -> the compiled `StateGraph` (graph.py) ->
`ToolRegistry` (tools/base.py) -> the three registered tools
(tools/calculator.py, tools/document_metadata.py, tools/knowledge_base.py).
Implemented in Milestone 6 — see
docs/architecture/decisions/008-agent-architecture.md. Multi-agent
workflows (A2A) and MCP remain out of scope for this module.
"""
