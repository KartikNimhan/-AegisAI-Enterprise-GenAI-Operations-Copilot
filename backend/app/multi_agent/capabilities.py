"""The static agent/capability registry — the single place that answers
"which agent provides which capability, and how do I reach it."

Deliberately static, not derived purely at runtime from discovered Agent
Cards: a discovered Card is still independently validated against this
same `AgentSpec.skill_id` at call time (see `app.a2a.client.A2AClient`),
so an agent is only ever called when *both* the static policy and its own
advertised Card agree — a compromised or buggy Card response alone can
never grant a new capability (see ADR 010, "Capability authorization").
"""

from __future__ import annotations

from dataclasses import dataclass

from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from app.a2a.agent_card import (
    CALCULATION_SKILL_ID,
    DOCUMENT_SKILL_ID,
    RESEARCH_SKILL_ID,
    SYNTHESIS_SKILL_ID,
)
from app.config import Settings

CAPABILITY_RESEARCH = "research"
CAPABILITY_DOCUMENT_ANALYSIS = "document_analysis"
CAPABILITY_CALCULATION = "calculation"
CAPABILITY_SYNTHESIS = "synthesis"

AGENT_RESEARCH = "research"
AGENT_DOCUMENT = "document"
AGENT_ANALYST = "analyst"


@dataclass(frozen=True)
class AgentSpec:
    agent_key: str
    expected_name_attr: str  # Settings attribute naming the expected Agent Card `name`
    card_path: str
    capabilities: tuple[str, ...]
    skill_id_by_capability: dict[str, str]


CAPABILITY_REGISTRY: dict[str, AgentSpec] = {
    AGENT_RESEARCH: AgentSpec(
        agent_key=AGENT_RESEARCH,
        expected_name_attr="research_agent_name",
        card_path=AGENT_CARD_WELL_KNOWN_PATH,
        capabilities=(CAPABILITY_RESEARCH,),
        skill_id_by_capability={CAPABILITY_RESEARCH: RESEARCH_SKILL_ID},
    ),
    AGENT_DOCUMENT: AgentSpec(
        agent_key=AGENT_DOCUMENT,
        expected_name_attr="document_agent_name",
        card_path="/api/v1/agents/document/card",
        capabilities=(CAPABILITY_DOCUMENT_ANALYSIS,),
        skill_id_by_capability={CAPABILITY_DOCUMENT_ANALYSIS: DOCUMENT_SKILL_ID},
    ),
    AGENT_ANALYST: AgentSpec(
        agent_key=AGENT_ANALYST,
        expected_name_attr="analyst_agent_name",
        card_path="/api/v1/agents/analyst/card",
        capabilities=(CAPABILITY_CALCULATION, CAPABILITY_SYNTHESIS),
        skill_id_by_capability={
            CAPABILITY_CALCULATION: CALCULATION_SKILL_ID,
            CAPABILITY_SYNTHESIS: SYNTHESIS_SKILL_ID,
        },
    ),
}


def agent_for_capability(capability: str) -> str | None:
    for agent_key, spec in CAPABILITY_REGISTRY.items():
        if capability in spec.capabilities:
            return agent_key
    return None


def expected_agent_name(settings: Settings, agent_key: str) -> str:
    return getattr(settings, CAPABILITY_REGISTRY[agent_key].expected_name_attr)
