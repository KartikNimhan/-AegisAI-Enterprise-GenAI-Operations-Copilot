"""Aggregates versioned (v1) business API routers.

`chat` (the LLM gateway) was wired up in Milestone 1; `conversations`
(persistence/history) in Milestone 2; `documents` (ingestion) in Milestone
3; `rag` (retrieval-augmented generation) in Milestone 5; `agents`
(single-agent LangGraph orchestration with tool calling) in Milestone 6.
Admin endpoints are reserved for an upcoming security/RBAC milestone and
are intentionally not wired up here yet. Health/readiness live outside
this router (see `app.api.v1.health`) since they are mounted at the root
path, unversioned.
"""

from fastapi import APIRouter

from app.api.v1 import agents, chat, conversations, documents, rag

api_router = APIRouter()
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(rag.router)
api_router.include_router(agents.router)
