"""The orchestrator's routing policy: a fully deterministic (regex/
keyword) decision of which capabilities a request needs — not an LLM
call. See docs/architecture/decisions/010-multi-agent-architecture.md,
"Routing", for why this milestone keeps routing deterministic rather than
"hybrid with a live model call": a regex/keyword policy is exhaustively
testable without a live Groq call, and this milestone's brief explicitly
warns against claiming real-model routing accuracy from a small synthetic
test set.

The policy never produces a capability outside the fixed set
(`research`, `document_analysis`, `calculation`, `synthesis`) or an empty
set ("direct" — the orchestrator answers without any specialist).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from app.multi_agent.capabilities import (
    CAPABILITY_CALCULATION,
    CAPABILITY_DOCUMENT_ANALYSIS,
    CAPABILITY_RESEARCH,
    CAPABILITY_SYNTHESIS,
)

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PERCENT_OF_PATTERN = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*of\s*(?P<base>\d+(?:\.\d+)?)", re.IGNORECASE
)
_ARITHMETIC_PATTERN = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*[\+\-\*/]\s*[-+]?\d+(?:\.\d+)?(?:\s*[\+\-\*/]\s*[-+]?\d+(?:\.\d+)?)*"
)
_COMPARE_KEYWORDS = ("compare", "comparison", "versus", " vs ")
_SMALL_TALK = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}


@dataclass(frozen=True)
class RoutingDecision:
    capabilities: tuple[str, ...]
    document_ids: list[uuid.UUID] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)


def route(message: str) -> RoutingDecision:
    stripped = message.strip()
    if stripped.lower().rstrip("!.") in _SMALL_TALK:
        return RoutingDecision(capabilities=())

    document_ids = _extract_document_ids(message)
    # A UUID's hex digit groups joined by hyphens otherwise look exactly
    # like a subtraction expression to `_ARITHMETIC_PATTERN` (e.g. the
    # "152-084718340" inside a UUID) — mask out matched UUIDs before
    # looking for arithmetic, so a document id never spuriously routes to
    # the Analyst.
    message_without_ids = _UUID_PATTERN.sub(" ", message)
    expressions = _extract_expressions(message_without_ids)
    wants_comparison = any(k in message.lower() for k in _COMPARE_KEYWORDS)

    capabilities: list[str] = []
    if document_ids:
        capabilities.append(CAPABILITY_DOCUMENT_ANALYSIS)
    if expressions or _looks_like_calculation_request(message):
        capabilities.append(CAPABILITY_CALCULATION)
    # Research is the general-purpose fallback for anything that isn't a
    # pure document lookup or a pure calculation — matching the brief's
    # own example 2 (a policy question with no document id or arithmetic).
    wants_research = not capabilities or wants_comparison or _looks_like_research_request(message)
    if wants_research and CAPABILITY_RESEARCH not in capabilities:
        capabilities.append(CAPABILITY_RESEARCH)

    if len(capabilities) > 1 or (wants_comparison and len(document_ids) > 1):
        capabilities.append(CAPABILITY_SYNTHESIS)

    return RoutingDecision(
        capabilities=tuple(capabilities), document_ids=document_ids, expressions=expressions
    )


def _extract_document_ids(message: str) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []
    for match in _UUID_PATTERN.finditer(message):
        try:
            candidate = uuid.UUID(match.group(0))
        except ValueError:  # pragma: no cover - regex already guarantees UUID shape
            continue
        if candidate not in seen:
            seen.append(candidate)
    return seen


def _extract_expressions(message: str) -> list[str]:
    percent_match = _PERCENT_OF_PATTERN.search(message)
    if percent_match:
        return [f"{percent_match.group('pct')}/100*{percent_match.group('base')}"]
    arithmetic_match = _ARITHMETIC_PATTERN.search(message)
    if arithmetic_match:
        return [arithmetic_match.group(0).strip()]
    return []


def _looks_like_calculation_request(message: str) -> bool:
    lowered = message.lower()
    return any(k in lowered for k in ("calculate", "compute", "how much is", "what is the sum"))


def _looks_like_research_request(message: str) -> bool:
    lowered = message.lower()
    return any(
        k in lowered
        for k in ("research", "policy", "what does", "says about", "summarize", "summarise")
    )
