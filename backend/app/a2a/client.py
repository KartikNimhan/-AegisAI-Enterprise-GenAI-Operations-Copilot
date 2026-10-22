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

import asyncio
import json
import re
import uuid
from urllib.parse import SplitResult, urlsplit

import httpx
import structlog
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from app.a2a.agent_card import RESEARCH_SKILL_ID
from app.a2a.exceptions import (
    A2AConnectionError,
    A2AError,
    A2AInvalidCardError,
    A2AResponseError,
    A2ATaskFailedError,
    A2ATimeoutError,
    A2AUntrustedAgentError,
)
from app.a2a.schemas import ResearchResult, ResearchSource
from app.config import Settings

logger = structlog.get_logger(__name__)


_DEFAULT_PORTS = {"http": 80, "https": 443}
# Whitespace, control characters, DEL and backslashes: `urllib` and `httpx` parse
# these differently (urllib silently strips tabs/newlines; WHATWG-style parsers
# treat `\` like `/`), so a URL containing any of them is never accepted.
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f\\]")


def _split_http_url(url: object, *, error: type[A2AError], what: str) -> SplitResult:
    """Parses `url` only if it is a clean, ASCII, credential-free http(s) URL.
    Every malformed input becomes `error` — never a raw `ValueError`."""
    if not isinstance(url, str) or not url.isascii() or _UNSAFE_URL_CHARS.search(url):
        raise error(f"{what} is not a clean ASCII URL")
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for an unparsable or out-of-range port
    except ValueError as exc:
        raise error(f"{what} is malformed") from exc
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise error(f"{what} must be an http(s) URL with a host")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise error(f"{what} must not embed credentials")
    if port == 0:
        raise error(f"{what} must not use port 0")
    return parts


def _origin(parts: SplitResult) -> tuple[str, str, int]:
    assert parts.hostname is not None
    # Compare the explicit port when there is one (`port or default` would turn
    # an explicit 0 into the default), else the scheme's default.
    port = parts.port if parts.port is not None else _DEFAULT_PORTS[parts.scheme]
    return parts.scheme, parts.hostname, port


async def _read_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    error: type[A2AError],
    json_payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> object:
    """Sends the request and returns the decoded JSON body, reading at most `max_bytes`.

    The body is consumed incrementally and abandoned as soon as it passes the cap, so a hostile or
    broken agent cannot make this process buffer an unbounded response. A declared Content-Length
    that is malformed or already over the cap is refused before any body is read. Every refusal is
    `error` with fixed text; nothing from the remote body is echoed."""
    async with client.stream(method, url, json=json_payload, headers=headers) as response:
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                raise error("The agent response had an invalid Content-Length") from None
            if declared_size < 0 or declared_size > max_bytes:
                raise error("The agent response is larger than the allowed size")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise error("The agent response is larger than the allowed size")
    try:
        return json.loads(bytes(body))
    except ValueError:  # includes JSONDecodeError and UnicodeDecodeError
        raise error("The agent response was not valid JSON") from None


def validate_task_shape(task: object) -> dict:
    """The structure every consumer of a task relies on, checked once at the boundary: a task is an
    object, `status` an object with a string `state`, `artifacts` a list of objects whose `parts`
    are lists of objects. Anything else is an `A2AResponseError`, not a stray TypeError later."""
    if not isinstance(task, dict):
        raise A2AResponseError("The agent returned an unusable task")
    status = task.get("status", {})
    if not isinstance(status, dict) or not isinstance(status.get("state", ""), str):
        raise A2AResponseError("The agent returned an unusable task status")
    message = status.get("message", {})
    if not isinstance(message, dict) or not _is_object_list(message.get("parts", [])):
        raise A2AResponseError("The agent returned an unusable task status")
    artifacts = task.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise A2AResponseError("The agent returned unusable task artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not _is_object_list(artifact.get("parts", [])):
            raise A2AResponseError("The agent returned unusable task artifacts")
    return task


def _is_object_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


class A2AClient:
    def __init__(self, *, settings: Settings, auth_token: str | None = None) -> None:
        self._settings = settings
        # The calling user's bearer token (Milestone 12). It is sent ONLY on the
        # task POST, and only after the task URL has been validated to lie within
        # the trusted agent's own origin; Agent Card fetches are never
        # authenticated (cards are public metadata). Never logged.
        self._auth_token = auth_token
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
            async with (
                asyncio.timeout(self._settings.a2a_total_timeout_seconds),
                httpx.AsyncClient(timeout=self._settings.a2a_client_timeout_seconds) as client,
            ):
                card = await _read_json(
                    client,
                    "GET",
                    url,
                    max_bytes=self._settings.a2a_max_response_bytes,
                    error=A2AInvalidCardError,
                )
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("a2a.card_failed", base_url=base_url, reason="timeout")
            raise A2ATimeoutError("The agent did not respond in time") from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # The exception text can carry URLs and addresses: log only its type.
            logger.warning(
                "a2a.card_failed", base_url=base_url, reason="connection", error=type(exc).__name__
            )
            raise A2AConnectionError("The agent could not be reached") from exc

        if not isinstance(card, dict):
            raise A2AInvalidCardError("The agent card is not a JSON object")
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
            # The remote's own error text is not forwarded (it is untrusted and can name internals).
            raise A2ATaskFailedError("The remote agent reported task failure")
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
        task_url = self._validated_task_url(base_url, card)
        run_id = uuid.uuid4()

        logger.info("a2a.task_started", run_id=str(run_id), base_url=base_url)
        try:
            async with (
                asyncio.timeout(self._settings.a2a_total_timeout_seconds),
                httpx.AsyncClient(timeout=self._settings.a2a_client_timeout_seconds) as client,
            ):
                # httpx does not follow redirects by default, so the token is
                # never re-sent to a redirect target; a 3xx fails raise_for_status.
                task = await _read_json(
                    client,
                    "POST",
                    task_url,
                    max_bytes=self._settings.a2a_max_response_bytes,
                    error=A2AResponseError,
                    json_payload=payload,
                    headers=self._auth_headers(),
                )
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="timeout")
            raise A2ATimeoutError("The agent did not respond in time") from exc
        except A2AResponseError:
            logger.warning("a2a.task_failed", run_id=str(run_id), reason="bad_response")
            raise
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # (`InvalidURL` is not an `HTTPError`; the URL was already validated
            # above, so this is defense in depth and never sent a request.)
            logger.warning(
                "a2a.task_failed",
                run_id=str(run_id),
                reason="connection",
                error=type(exc).__name__,
            )
            raise A2AConnectionError("The agent could not be reached") from exc

        validated = validate_task_shape(task)
        logger.info("a2a.task_completed", run_id=str(run_id), base_url=base_url)
        return validated

    def _auth_headers(self) -> dict[str, str] | None:
        if not self._auth_token:
            return None
        return {"Authorization": f"Bearer {self._auth_token}"}

    def _validated_task_url(self, base_url: str, card: dict) -> str:
        """The task URL comes from the (remote-supplied) Agent Card, so it is
        untrusted until proven to point at the trusted agent itself. It must be
        a clean ASCII http(s) URL (no whitespace/control characters/backslashes,
        no credentials, a valid non-zero port), with the same scheme, host and
        port as the allowlisted `base_url`, no query or fragment, and a path of
        exactly the form `<api prefix>/agents/<name>/tasks` — the restricted
        character set rules out dot segments, percent-encoded tricks, `;`
        parameters and empty segments, so the URL has one meaning for every
        parser. Anything else is rejected BEFORE any request is made, so neither
        the payload nor the caller's bearer token can be sent to a destination
        the card chose."""
        try:
            raw_url = card["supportedInterfaces"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise A2AInvalidCardError("Agent card has no usable task URL") from exc
        candidate = _split_http_url(raw_url, error=A2AInvalidCardError, what="Agent card task URL")
        trusted = _split_http_url(
            base_url, error=A2AUntrustedAgentError, what="The trusted agent base URL"
        )
        if _origin(candidate) != _origin(trusted):
            raise A2AInvalidCardError("Agent card task URL is outside the trusted agent origin")
        # (Checked on the raw string too: a bare trailing `?` parses to an empty query.)
        if "?" in raw_url or "#" in raw_url or candidate.query or candidate.fragment:
            raise A2AInvalidCardError("Agent card task URL must not carry a query or fragment")
        prefix = re.escape(self._settings.api_v1_prefix.rstrip("/"))
        if not re.fullmatch(rf"{prefix}/agents/[A-Za-z0-9_-]+/tasks", candidate.path):
            raise A2AInvalidCardError("Agent card task URL is not an agents task path")
        return raw_url


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
    try:
        return _parse_research_result(validate_task_shape(task))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise A2AResponseError("The agent returned an unusable research result") from None


def _parse_research_result(task: dict) -> ResearchResult:
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
