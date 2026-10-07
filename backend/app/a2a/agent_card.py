"""Builds the Research Agent's A2A Agent Card.

Uses `a2a.types` directly (the installed `a2a-sdk==1.2.1`'s own protobuf
message classes) to construct a real, spec-shaped card — field names and
the resulting JSON (verified via the SDK's own `agent_card_to_dict`
serializer: `supportedInterfaces`, `protocolBinding`, `defaultInputModes`,
`defaultOutputModes`, `skills`, `capabilities`, `protocolVersion`,
`preferredTransport`) are not invented. See
docs/architecture/decisions/009-mcp-a2a-architecture.md, "Agent Card", for
the full verification trail and the A2A protocol version this targets
(`0.3`, confirmed from the SDK's own `protocolVersion` default).
"""

from __future__ import annotations

from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from app.config import Settings

RESEARCH_SKILL_ID = "research_question"


def build_research_agent_card(settings: Settings, *, base_url: str) -> AgentCard:
    card = AgentCard(
        name=settings.research_agent_name,
        description=(
            "Given a research question, searches the AegisAI knowledge base "
            "and returns a structured research result with sources."
        ),
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["application/json"],
    )
    card.capabilities.CopyFrom(AgentCapabilities(streaming=False, push_notifications=False))
    card.skills.append(
        AgentSkill(
            id=RESEARCH_SKILL_ID,
            name="Research a question",
            description=(
                "Searches the organization's ingested documents for evidence "
                "relevant to a question and returns a synthesized, sourced answer."
            ),
            tags=["research", "rag", "knowledge-base"],
        )
    )
    card.supported_interfaces.append(
        AgentInterface(
            url=f"{base_url}/api/v1/agents/research/tasks",
            protocol_binding="JSONRPC",
        )
    )
    return card


def agent_card_to_json_dict(card: AgentCard) -> dict:
    """The SDK's own serializer — not a hand-rolled dict, so the JSON
    shape served to a real A2A client matches what `a2a-sdk` itself
    produces and expects."""
    return agent_card_to_dict(card)
