"""Aggregates versioned (v1) business API routers.

`chat` (the LLM gateway) is wired up as of Milestone 1. Documents,
conversations, agents, and admin endpoints are reserved for upcoming
milestones (RAG, LangGraph agents, security/RBAC) and are intentionally not
wired up here yet. Health/readiness live outside this router (see
`app.api.v1.health`) since they are mounted at the root path, unversioned.
"""

from fastapi import APIRouter

from app.api.v1 import chat

api_router = APIRouter()
api_router.include_router(chat.router)
