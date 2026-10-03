"""Aggregates versioned (v1) business API routers.

`chat` (the LLM gateway) was wired up in Milestone 1; `conversations`
(persistence/history) in Milestone 2. Documents, agents, and admin
endpoints are reserved for upcoming milestones (RAG, LangGraph agents,
security/RBAC) and are intentionally not wired up here yet. Health/readiness
live outside this router (see `app.api.v1.health`) since they are mounted
at the root path, unversioned.
"""

from fastapi import APIRouter

from app.api.v1 import chat, conversations

api_router = APIRouter()
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
