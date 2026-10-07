"""Builds Agent Cards for every A2A-exposed agent in this project
(Research — Milestone 7; Document, Analyst — Milestone 8).

Uses `a2a.types` directly (the installed `a2a-sdk==1.2.1`'s own protobuf
message classes) to construct real, spec-shaped cards — field names and
the resulting JSON (verified via the SDK's own `agent_card_to_dict`
serializer: `supportedInterfaces`, `protocolBinding`, `defaultInputModes`,
`defaultOutputModes`, `skills`, `capabilities`, `protocolVersion`,
`preferredTransport`) are not invented. See
docs/architecture/decisions/009-mcp-a2a-architecture.md, "Agent Card", for
the full verification trail and the A2A protocol version this targets
(`0.3`, confirmed from the SDK's own `protocolVersion` default).

Only the Research Agent's card is served at the A2A well-known path
(`/.well-known/agent-card.json`) — that path is a per-*origin* convention
(one well-known document per host), and all three agents in this
milestone are served by the same origin. The Document and Analyst Agent
Cards are instead served at their own versioned convenience path, the
same pattern `/api/v1/agents/research/card` already uses — see ADR 010,
"Agent Card", for why.
"""

from __future__ import annotations

from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from app.config import Settings

RESEARCH_SKILL_ID = "research_question"
DOCUMENT_SKILL_ID = "document_analysis"
CALCULATION_SKILL_ID = "calculation"
SYNTHESIS_SKILL_ID = "synthesis"


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


def build_document_agent_card(settings: Settings, *, base_url: str) -> AgentCard:
    card = AgentCard(
        name=settings.document_agent_name,
        description=(
            "Given one or more document ids, returns safe metadata (filename, "
            "type, status, page/character counts) for each — never raw "
            "content, embeddings, or filesystem paths."
        ),
        version="1.0.0",
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    )
    card.capabilities.CopyFrom(AgentCapabilities(streaming=False, push_notifications=False))
    card.skills.append(
        AgentSkill(
            id=DOCUMENT_SKILL_ID,
            name="Analyze documents",
            description=(
                "Looks up safe metadata for one or more ingested documents by "
                "id, suitable for answering document-specific questions or "
                "comparing multiple documents' metadata."
            ),
            tags=["documents", "metadata"],
        )
    )
    card.supported_interfaces.append(
        AgentInterface(
            url=f"{base_url}/api/v1/agents/document/tasks",
            protocol_binding="JSONRPC",
        )
    )
    return card


def build_analyst_agent_card(settings: Settings, *, base_url: str) -> AgentCard:
    card = AgentCard(
        name=settings.analyst_agent_name,
        description=(
            "Performs safe arithmetic and synthesizes a final answer from "
            "structured evidence supplied by other agents. Never accesses "
            "arbitrary external systems itself."
        ),
        version="1.0.0",
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    )
    card.capabilities.CopyFrom(AgentCapabilities(streaming=False, push_notifications=False))
    card.skills.append(
        AgentSkill(
            id=CALCULATION_SKILL_ID,
            name="Calculate",
            description="Evaluates safe arithmetic expressions (AST-based, never eval/exec).",
            tags=["calculator", "arithmetic"],
        )
    )
    card.skills.append(
        AgentSkill(
            id=SYNTHESIS_SKILL_ID,
            name="Synthesize",
            description=(
                "Synthesizes a final answer from structured evidence supplied "
                "by other agents (e.g. research findings, document metadata), "
                "treating that evidence as untrusted data, not instructions."
            ),
            tags=["synthesis", "reasoning"],
        )
    )
    card.supported_interfaces.append(
        AgentInterface(
            url=f"{base_url}/api/v1/agents/analyst/tasks",
            protocol_binding="JSONRPC",
        )
    )
    return card


def agent_card_to_json_dict(card: AgentCard) -> dict:
    """The SDK's own serializer — not a hand-rolled dict, so the JSON
    shape served to a real A2A client matches what `a2a-sdk` itself
    produces and expects."""
    return agent_card_to_dict(card)
