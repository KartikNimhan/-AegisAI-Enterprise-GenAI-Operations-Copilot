"""Aggregates versioned (v1) business API routers.

Authentication (Milestone 12, Phase 1a): `api_router` carries
`get_current_principal` as a router-level dependency, so EVERY route included
here — including any added in future — requires a valid, active user. The
only unauthenticated versioned routes are the three Agent Cards, which live
on `public_api_router` (explicit, non-sensitive metadata; A2AClient fetches
them without credentials). Health probes and the well-known agent card are
mounted directly in `app.main`. There is no bypass switch.

`chat` (the LLM gateway) was wired up in Milestone 1; `conversations`
(persistence/history) in Milestone 2; `documents` (ingestion) in Milestone
3; `rag` (retrieval-augmented generation) in Milestone 5; `agents`
(single-agent LangGraph orchestration with tool calling) in Milestone 6;
`research_agent` (the A2A Research Agent's versioned endpoints — its
unversioned well-known Agent Card path is mounted separately, see
`app.main`) in Milestone 7; `document_agent`/`analyst_agent` (the other
two specialized A2A agents) and `multi_agent` (the orchestrator endpoint)
in Milestone 8; `operations` (a read-only document-status summary) and
`system` (a read-only status aggregation reusing `/health/ready`'s own
checks) in Milestone 9, added for the Copilot UI's dashboard/status pages;
`auth` (the caller's own identity) in Milestone 12.
Admin endpoints are reserved for a later security phase and are
intentionally not wired up here yet. Health/readiness live outside this
router (see `app.api.v1.health`) since they are mounted at the root path,
unversioned.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import (
    agents,
    analyst_agent,
    auth,
    chat,
    conversations,
    document_agent,
    documents,
    operations,
    rag,
    system,
)
from app.api.v1 import multi_agent as multi_agent_module
from app.api.v1 import research_agent as research_agent_module
from app.core.security import get_current_principal

# Public: Agent Card metadata only.
public_api_router = APIRouter()
public_api_router.include_router(research_agent_module.card_router)
public_api_router.include_router(document_agent.card_router)
public_api_router.include_router(analyst_agent.card_router)

# Authenticated: everything else.
api_router = APIRouter(dependencies=[Depends(get_current_principal)])
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(rag.router)
api_router.include_router(agents.router)
api_router.include_router(research_agent_module.router)
api_router.include_router(document_agent.router)
api_router.include_router(analyst_agent.router)
api_router.include_router(multi_agent_module.router)
api_router.include_router(operations.router)
api_router.include_router(system.router)
