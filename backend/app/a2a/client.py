"""The orchestrator-side A2A client/adapter: fetches and validates a
trusted agent's Card, then submits a research task and parses the result.

Security model (see ADR 009, "A2A security" and `Settings.trusted_a2a_agents`):
a `base_url` is only ever one explicitly configured at startup — never a
user-supplied or runtime-discovered endpoint. The fetched Agent Card is a
second, independent trust signal: its `name` must match
`Settings.research_agent_name` and it must advertise the
`research_question` skill before any task is ever submitted to it.

Transport: a plain HTTP `httpx.AsyncClient` POST, not the full
`a2a-sdk` client transport stack (JSON-RPC/gRPC/REST dispatchers,
interceptors, client factories) — see
docs/architecture/decisions/009-mcp-a2a-architecture.md, "Why a thin HTTP
client rather than the full a2a-sdk client", for why that framework is
disproportionate to one small, synchronous Research Agent.
"""

from __future__ import annotations

import uuid

import httpx
import structlog
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from app.a2a.agent_card import RESEARCH_SKILL_ID
from app.a2a.exceptions import (
    A2AConnectionError,
    A2AInvalidCardError,
    A2ATaskFailedError,
    A2ATimeoutError,
    A2AUntrustedAgentError,
)
from app.a2a.schemas import ResearchResult, ResearchSource
from app.config import Settings

logger = structlog.get_logger(__name__)


class A2AClient:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def _ensure_trusted(self, base_url: str) -> None:
        if base_url not in self._settings.trusted_a2a_agents:
            raise A2AUntrustedAgentError(f"{base_url!r} is not in trusted_a2a_agents")

    async def fetch_agent_card(self, base_url: str) -> dict:
        self._ensure_trusted(base_url)
        url = f"{base_url}{AGENT_CARD_WELL_KNOWN_PATH}"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.a2a_client_timeout_seconds
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                card = response.json()
        except httpx.TimeoutException as exc:
            raise A2ATimeoutError(f"Timed out fetching agent card from {base_url}") from exc
        except httpx.HTTPError as exc:
            raise A2AConnectionError(f"Could not reach agent at {base_url}: {exc}") from exc

        self._validate_card(card)
        logger.info("a2a.agent_discovered", base_url=base_url, agent_name=card.get("name"))
        return card

    def _validate_card(self, card: dict) -> None:
        if card.get("name") != self._settings.research_agent_name:
            raise A2AInvalidCardError(
                f"Agent card name {card.get('name')!r} does not match "
                f"the expected {self._settings.research_agent_name!r}"
            )
        skill_ids = {skill.get("id") for skill in card.get("skills", [])}
        if RESEARCH_SKILL_ID not in skill_ids:
            raise A2AInvalidCardError(
                f"Agent card does not advertise the {RESEARCH_SKILL_ID!r} skill"
            )
        if not card.get("supportedInterfaces"):
            raise A2AInvalidCardError("Agent card has no supported interfaces")

    async def submit_research_task(self, base_url: str, *, question: str) -> ResearchResult:
        self._ensure_trusted(base_url)
        card = await self.fetch_agent_card(base_url)
        task_url = card["supportedInterfaces"][0]["url"]
        run_id = uuid.uuid4()

        logger.info("a2a.task_started", run_id=str(run_id), base_url=base_url)
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.a2a_client_timeout_seconds
            ) as client:
                response = await client.post(task_url, json={"question": question})
                response.raise_for_status()
                task = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="timeout")
            raise A2ATimeoutError(f"Timed out submitting task to {base_url}") from exc
        except httpx.HTTPError as exc:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="connection")
            raise A2AConnectionError(f"Could not reach agent at {base_url}: {exc}") from exc

        result = _task_to_research_result(task)
        if result.status != "completed":
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="task_failed")
            raise A2ATaskFailedError(result.error or "The remote agent reported task failure")

        logger.info("a2a.task_completed", run_id=str(run_id), base_url=base_url)
        return result


def _task_to_research_result(task: dict) -> ResearchResult:
    """Parses the A2A `Task` JSON (as served by `app.a2a.tasks.task_to_dict`)
    back into a `ResearchResult` — never trusts the shape blindly; a
    malformed response (missing `status`, an artifact with no `data` part)
    is treated as a task failure, not an exception that could crash the
    orchestrator.
    """
    status = task.get("status", {})
    state = status.get("state", "")

    if state != "TASK_STATE_COMPLETED":
        error_message = None
        message = status.get("message", {})
        for part in message.get("parts", []):
            if "text" in part:
                error_message = part["text"]
                break
        return ResearchResult(status="failed", answer="", error=error_message)

    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            data = part.get("data")
            if data is None:
                continue
            sources = [
                ResearchSource(
                    chunk_id=uuid.UUID(s["chunk_id"]),
                    document_id=uuid.UUID(s["document_id"]),
                    filename=s["filename"],
                    # The wire format round-trips numbers through a
                    # protobuf `Value` (google.protobuf.Struct), which only
                    # has a double — an integer page number comes back as
                    # e.g. `2.0`, not `2`. Coerce it back explicitly rather
                    # than silently storing a float where an int is typed.
                    page_number=(
                        int(s["page_number"]) if s.get("page_number") is not None else None
                    ),
                    similarity=s.get("similarity", 0.0),
                )
                for s in data.get("sources", [])
            ]
            return ResearchResult(
                status="completed", answer=data.get("answer", ""), sources=sources
            )

    return ResearchResult(
        status="failed", answer="", error="The remote agent's response had no result artifact"
    )
