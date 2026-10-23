"""Each turn loads only the history window it can replay, never the whole conversation.

Regression: chat, RAG and agent turns loaded every message of a conversation, then kept at most
`CHAT_HISTORY_MAX_MESSAGES` of them, so the cost of a turn grew with the conversation's length.
"""

from __future__ import annotations

from app.llm.schemas import ModelRole
from app.prompts.history import DEFAULT_MAX_MESSAGES

from ..agents.doubles import ScriptedAgentGateway, make_final_completion
from ..agents.test_agent_service import make_service as make_agent_service
from ..agents.test_agent_service import make_settings as make_agent_settings
from ..rag.doubles import FakeRetrievalStrategy, ScriptedRAGGateway, make_result
from ..rag.test_rag_service import make_completion as make_rag_completion
from ..rag.test_rag_service import make_service as make_rag_service
from .doubles import ScriptedChatGateway
from .test_chat_service import make_completion as make_chat_completion
from .test_chat_service import make_service as make_chat_service


async def test_a_chat_turn_loads_only_the_history_window() -> None:
    service, _conversations, messages, _session = make_chat_service(
        ScriptedChatGateway(completion=make_chat_completion())
    )

    await service.send_message(conversation_id=None, message="hi", model_role=ModelRole.PRIMARY)

    assert messages.recent_limits == [DEFAULT_MAX_MESSAGES]


async def test_a_rag_turn_loads_only_the_history_window() -> None:
    service, _conversations, messages, _session = make_rag_service(
        gateway=ScriptedRAGGateway(completion=make_rag_completion()),
        strategy=FakeRetrievalStrategy(results=[make_result()]),
    )

    await service.answer(conversation_id=None, message="q", model_role=ModelRole.PRIMARY)

    assert messages.recent_limits == [DEFAULT_MAX_MESSAGES]


async def test_an_agent_run_loads_only_the_configured_window() -> None:
    settings = make_agent_settings(chat_history_max_messages=7)
    service, _conversations, messages = await make_agent_service(
        gateway=ScriptedAgentGateway(effects=[make_final_completion("done")]),
        settings=settings,
    )

    await service.run(conversation_id=None, message="q")

    assert messages.recent_limits == [7]
