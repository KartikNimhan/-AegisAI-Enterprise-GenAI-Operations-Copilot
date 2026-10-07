"""Agent-to-Agent (A2A) interoperability: one small, specialized remote
Research Agent, reached through the real A2A protocol boundary (an Agent
Card + a task lifecycle), not by importing its implementation directly.

`agent_card.py` builds the real `a2a.types.AgentCard` (verified against
the installed `a2a-sdk==1.2.1`, A2A protocol version `0.3`);
`research_agent.py` is the agent's own logic (reuses `RetrievalService`/
`LLMGateway`, no duplicated retrieval/generation); `client.py` is the
orchestrator-side adapter the M6 agent's delegation tool calls through.
See docs/architecture/decisions/009-mcp-a2a-architecture.md.
"""
