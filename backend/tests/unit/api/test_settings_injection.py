"""Service factories take the application's settings through dependency injection.

`create_app(settings)` plus a `get_settings` override must reach chat, RAG and agent services; a
factory that called `get_settings()` itself would silently use the process-wide cached settings.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agents.service import get_agent_service
from app.auth.scope import AccessScope
from app.config import Settings
from app.rag.service import get_rag_service
from app.services.chat_service import get_chat_service

SCOPE = AccessScope.for_user(user_id=uuid.uuid4(), organization_id=uuid.uuid4())


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, debug=False, **overrides)  # type: ignore[call-arg]


def test_the_chat_factory_uses_the_injected_history_limits() -> None:
    service = get_chat_service(
        session=None,  # type: ignore[arg-type]
        scope=SCOPE,
        gateway=None,  # type: ignore[arg-type]
        settings=settings(chat_history_max_messages=3, chat_history_max_chars=1234),
    )

    limits = service._prompt_builder._history_limits  # type: ignore[attr-defined]
    assert (limits.max_messages, limits.max_chars) == (3, 1234)


def test_the_rag_factory_uses_the_injected_context_and_history_limits() -> None:
    service = get_rag_service(
        session=None,  # type: ignore[arg-type]
        scope=SCOPE,
        gateway=None,  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
        settings=settings(rag_max_context_chars=4321, chat_history_max_messages=5),
    )

    assert service._context_assembler._max_context_chars == 4321  # type: ignore[attr-defined]
    assert service._prompt_builder._history_limits.max_messages == 5  # type: ignore[attr-defined]


async def test_the_agent_factory_uses_the_injected_settings() -> None:
    injected = settings(agent_max_steps=3, agent_memory_enabled=False)

    service = await get_agent_service(
        session=None,  # type: ignore[arg-type]
        scope=SCOPE,
        gateway=None,  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
        bearer_token="test-token",
        settings=injected,
    )

    assert service._settings is injected  # type: ignore[attr-defined]
