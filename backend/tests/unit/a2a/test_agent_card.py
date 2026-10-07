"""Unit tests for the Research Agent's A2A Agent Card: shape, the skill it
advertises, and that its serialized JSON matches what `A2AClient._validate_card`
expects (see test_a2a_client.py for the client side of that contract).
"""

from __future__ import annotations

from app.a2a.agent_card import RESEARCH_SKILL_ID, agent_card_to_json_dict, build_research_agent_card
from app.config import Settings


def _settings() -> Settings:
    return Settings()


def test_card_name_matches_settings() -> None:
    settings = _settings()
    card = build_research_agent_card(settings, base_url="http://localhost:8000")
    assert card.name == settings.research_agent_name


def test_card_advertises_the_research_question_skill() -> None:
    card = build_research_agent_card(_settings(), base_url="http://localhost:8000")
    skill_ids = {skill.id for skill in card.skills}
    assert RESEARCH_SKILL_ID in skill_ids


def test_card_has_a_supported_interface_pointing_at_the_tasks_endpoint() -> None:
    card = build_research_agent_card(_settings(), base_url="http://localhost:8000")
    assert len(card.supported_interfaces) == 1
    interface = card.supported_interfaces[0]
    assert interface.url == "http://localhost:8000/api/v1/agents/research/tasks"
    assert interface.protocol_binding == "JSONRPC"


def test_card_json_dict_round_trip_has_the_fields_the_client_validates() -> None:
    card = build_research_agent_card(_settings(), base_url="http://localhost:8000")
    payload = agent_card_to_json_dict(card)

    assert payload["name"] == _settings().research_agent_name
    skill_ids = {skill["id"] for skill in payload["skills"]}
    assert RESEARCH_SKILL_ID in skill_ids
    assert payload["supportedInterfaces"]
    assert payload["supportedInterfaces"][0]["url"].endswith("/api/v1/agents/research/tasks")


def test_card_does_not_expose_any_secret_or_internal_configuration() -> None:
    card = build_research_agent_card(_settings(), base_url="http://localhost:8000")
    payload = agent_card_to_json_dict(card)
    serialized = str(payload).lower()
    for forbidden in ("api_key", "password", "secret", "database_url", "groq"):
        assert forbidden not in serialized
