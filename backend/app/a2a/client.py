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
        # Keyed by (base_url, card_path). Agent Cards are static for the
        # lifetime of one `A2AClient` in this reference deployment (the
        # three agents never change their advertised capabilities at
        # runtime), so this avoids refetching the same Card on every
        # retry of the same agent within one workflow (see ADR 010,
        # "Agent Card Discovery": "do not fetch Agent Cards unnecessarily
        # for every task"). Only a *successful, validated* Card is ever
        # cached — a failure is never cached, so a transient fetch error
        # doesn't poison every subsequent retry.
        self._card_cache: dict[tuple[str, str], dict] = {}

    def _ensure_trusted(self, base_url: str) -> None:
        if base_url not in self._settings.trusted_a2a_agents:
            raise A2AUntrustedAgentError(f"{base_url!r} is not in trusted_a2a_agents")

    async def fetch_agent_card(self, base_url: str) -> dict:
        return await self.fetch_agent_card_at(
            base_url,
            card_path=AGENT_CARD_WELL_KNOWN_PATH,
            expected_name=self._settings.research_agent_name,
            expected_skill_id=RESEARCH_SKILL_ID,
        )

    async def fetch_agent_card_at(
        self, base_url: str, *, card_path: str, expected_name: str, expected_skill_id: str
    ) -> dict:
        """The generic form `fetch_agent_card` delegates to, and the one
        Milestone 8's multi-agent orchestrator uses directly for the
        Document/Analyst agents — their cards are served at their own
        versioned path, not the well-known one (see ADR 010, "Agent
        Card": only one well-known path can exist per origin, and all
        three agents in this project share an origin)."""
        self._ensure_trusted(base_url)
        cache_key = (base_url, card_path)
        cached = self._card_cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{base_url}{card_path}"
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

        _validate_card(card, expected_name=expected_name, expected_skill_id=expected_skill_id)
        logger.info("a2a.agent_discovered", base_url=base_url, agent_name=card.get("name"))
        self._card_cache[cache_key] = card
        return card

    async def submit_research_task(self, base_url: str, *, question: str) -> ResearchResult:
        task = await self.submit_task(
            base_url,
            card_path=AGENT_CARD_WELL_KNOWN_PATH,
            expected_agent_name=self._settings.research_agent_name,
            expected_skill_id=RESEARCH_SKILL_ID,
            payload={"question": question},
        )
        result = parse_research_result(task)
        if result.status != "completed":
            logger.warning("a2a.task_failed", base_url=base_url, reason="task_failed")
            raise A2ATaskFailedError(result.error or "The remote agent reported task failure")
        return result

    async def submit_task(
        self,
        base_url: str,
        *,
        card_path: str,
        expected_agent_name: str,
        expected_skill_id: str,
        payload: dict,
    ) -> dict:
        """The generic task-submission path Milestone 8's orchestrator
        uses for any trusted agent (Research, Document, Analyst):
        fetches and validates that agent's own Card, then POSTs `payload`
        to its advertised task URL — the URL is never hardcoded here,
        only discovered from the Card (see ADR 009, "A2A agent
        discovery"). Returns the raw parsed `Task` JSON; the caller
        parses its own agent's artifact shape (`submit_research_task`
        above does this for the Research Agent; Milestone 8's
        agent-specific A2A adapters do it for Document/Analyst)."""
        self._ensure_trusted(base_url)
        card = await self.fetch_agent_card_at(
            base_url,
            card_path=card_path,
            expected_name=expected_agent_name,
            expected_skill_id=expected_skill_id,
        )
        task_url = card["supportedInterfaces"][0]["url"]
        run_id = uuid.uuid4()

        logger.info("a2a.task_started", run_id=str(run_id), base_url=base_url)
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.a2a_client_timeout_seconds
            ) as client:
                response = await client.post(task_url, json=payload)
                response.raise_for_status()
                task = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="timeout")
            raise A2ATimeoutError(f"Timed out submitting task to {base_url}") from exc
        except httpx.HTTPError as exc:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="connection")
            raise A2AConnectionError(f"Could not reach agent at {base_url}: {exc}") from exc

        logger.info("a2a.task_completed", run_id=str(run_id), base_url=base_url)
        return task


def _validate_card(card: dict, *, expected_name: str, expected_skill_id: str) -> None:
    if card.get("name") != expected_name:
        raise A2AInvalidCardError(
            f"Agent card name {card.get('name')!r} does not match the expected {expected_name!r}"
        )
    skill_ids = {skill.get("id") for skill in card.get("skills", [])}
    if expected_skill_id not in skill_ids:
        raise A2AInvalidCardError(f"Agent card does not advertise the {expected_skill_id!r} skill")
    if not card.get("supportedInterfaces"):
        raise A2AInvalidCardError("Agent card has no supported interfaces")


def parse_research_result(task: dict) -> ResearchResult:
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
                status="completed",
                answer=data.get("answer", ""),
                sources=sources,
                token_usage=data.get("token_usage"),
            )

    return ResearchResult(
        status="failed", answer="", error="The remote agent's response had no result artifact"
    )
