"""Aggregates versioned (v1) business API routers.

`chat` (the LLM gateway) was wired up in Milestone 1; `conversations`
(persistence/history) in Milestone 2; `documents` (ingestion) in Milestone
3; `rag` (retrieval-augmented generation) in Milestone 5; `agents`
(single-agent LangGraph orchestration with tool calling) in Milestone 6;
`research_agent` (the A2A Research Agent's versioned endpoints — its
unversioned well-known Agent Card path is mounted separately, see
`app.main`) in Milestone 7; `document_agent`/`analyst_agent` (the other
two specialized A2A agents) and `multi_agent` (the orchestrator endpoint)
in Milestone 8. Admin endpoints are reserved for an upcoming
security/RBAC milestone and are intentionally not wired up here yet.
Health/readiness live outside this router (see `app.api.v1.health`) since
they are mounted at the root path, unversioned.
"""

from fastapi import APIRouter

from app.api.v1 import agents, analyst_agent, chat, conversations, document_agent, documents, rag
from app.api.v1 import multi_agent as multi_agent_module
from app.api.v1 import research_agent as research_agent_module

api_router = APIRouter()
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(rag.router)
api_router.include_router(agents.router)
api_router.include_router(research_agent_module.router)
api_router.include_router(document_agent.router)
api_router.include_router(analyst_agent.router)
api_router.include_router(multi_agent_module.router)
