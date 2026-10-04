"""Unit tests for AgentService + the LangGraph graph it builds: direct
answers, single/multi tool calls, tool failure handling, maximum-step and
maximum-tool-call protection, timeout behavior, conversation integration,
and the untrusted-tool-output (prompt injection) guarantee — all against
fakes, no real DB, model, or Groq call.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agents.exceptions import AgentTimeoutError
from app.agents.schemas import (
    STATUS_COMPLETED,
    STATUS_MAX_STEPS_EXCEEDED,
    STATUS_MAX_TOOL_CALLS_EXCEEDED,
)
from app.agents.service import AgentService
from app.config import Settings
from app.core.exceptions import NotFoundError
from app.llm.exceptions import LLMTimeoutError
from app.llm.schemas import CompletionResponse
from app.rag.retrieval.service import RetrievalService

from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository
from ..services.doubles import FakeConversationRepository, FakeMessageRepository, FakeSession
from .doubles import (
    ScriptedAgentGateway,
    make_final_completion,
    make_multi_tool_call_completion,
    make_tool_call_completion,
)


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "agent_max_steps": 8,
        "agent_max_tool_calls": 10,
        "agent_timeout_seconds": 5.0,
        "rag_top_k": 5,
        "rag_max_results": 20,
        "rag_similarity_threshold": 0.3,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def make_service(
    *, gateway: ScriptedAgentGateway, settings: Settings | None = None
) -> tuple[AgentService, FakeConversationRepository, FakeMessageRepository]:
    resolved_settings = settings or make_settings()
    conversations = FakeConversationRepository()
    messages = FakeMessageRepository()
    documents = FakeDocumentRepository()
    retrieval = RetrievalService(
        strategy=FakeRetrievalStrategy(results=[]), settings=resolved_settings
    )
    service = AgentService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=resolved_settings,
        gateway=gateway,
        conversations=conversations,  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
        documents=documents,  # type: ignore[arg-type]
        retrieval=retrieval,
    )
    return service, conversations, messages


# -- Direct answer, no tools ---------------------------------------------------


async def test_direct_answer_without_any_tool_call() -> None:
    gateway = ScriptedAgentGateway(effects=[make_final_completion("4")])
    service, _conversations, messages = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="What is 2 + 2 conceptually?")

    assert result.status == STATUS_COMPLETED
    assert result.answer == "4"
    assert result.steps == 1
    assert result.tool_calls == []
    assert len(gateway.chat_completion_calls) == 1
    assert len(messages.messages) == 2  # user + assistant


# -- Single tool call -----------------------------------------------------------


async def test_single_tool_call_then_final_answer() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "250*0.18"}),
            make_final_completion("The result is 45."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="What is 250 * 0.18?")

    assert result.status == STATUS_COMPLETED
    assert result.answer == "The result is 45."
    assert result.steps == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "calculator"
    assert result.tool_calls[0].success_count == 1
    assert len(gateway.chat_completion_calls) == 2


# -- Multiple / sequential tool calls --------------------------------------------


async def test_multiple_sequential_tool_calls() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "1+1"}),
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "2+2"}),
            make_final_completion("Done."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="Compute two things")

    assert result.status == STATUS_COMPLETED
    assert result.steps == 3
    assert result.tool_calls[0].call_count == 2


async def test_multiple_tool_calls_in_a_single_step() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_multi_tool_call_completion(
                calls=[
                    ("calculator", {"expression": "1+1"}),
                    ("calculator", {"expression": "2+2"}),
                ]
            ),
            make_final_completion("Done."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="Compute two things at once")

    assert result.status == STATUS_COMPLETED
    assert result.steps == 2
    assert result.tool_calls[0].call_count == 2


# -- Tool failure / invalid arguments --------------------------------------------


async def test_tool_failure_is_surfaced_to_the_model_and_run_still_completes() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "1/0"}),
            make_final_completion("I couldn't compute that."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="What is 1/0?")

    assert result.status == STATUS_COMPLETED
    assert result.tool_calls[0].failure_count == 1
    assert result.tool_calls[0].success_count == 0
    # The second LLM call must have seen the tool's error as a message.
    second_call_messages = gateway.chat_completion_calls[1]["messages"]
    assert any(
        "validation_error" in m.content or "false" in m.content.lower()
        for m in second_call_messages
    )


async def test_invalid_tool_arguments_produce_a_controlled_error_not_a_crash() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"wrong_field": "oops"}),
            make_final_completion("Something went wrong with that calculation."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="question")

    assert result.status == STATUS_COMPLETED
    assert result.tool_calls[0].failure_count == 1


async def test_unknown_tool_name_produces_a_controlled_error() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="does_not_exist", arguments={}),
            make_final_completion("I don't have that capability."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="question")

    assert result.status == STATUS_COMPLETED
    assert result.tool_calls[0].name == "does_not_exist"
    assert result.tool_calls[0].failure_count == 1


# -- Maximum steps / maximum tool calls -------------------------------------------


async def test_maximum_steps_protection_stops_an_infinite_tool_loop() -> None:
    # The model keeps requesting the same tool forever; agent_max_steps=3
    # must force a controlled stop rather than looping forever.
    effects: list[CompletionResponse | Exception] = [
        make_tool_call_completion(tool_name="calculator", arguments={"expression": "1+1"})
        for _ in range(10)
    ]
    gateway = ScriptedAgentGateway(effects=effects)
    service, *_rest = make_service(gateway=gateway, settings=make_settings(agent_max_steps=3))

    result = await service.run(conversation_id=None, message="loop forever")

    assert result.status == STATUS_MAX_STEPS_EXCEEDED
    assert result.steps == 3
    # Only 3 LLM calls should have happened — the graph must not have
    # continued past the step limit.
    assert len(gateway.chat_completion_calls) == 3


async def test_maximum_tool_calls_protection() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_multi_tool_call_completion(
                calls=[("calculator", {"expression": "1+1"}) for _ in range(5)]
            )
        ]
    )
    service, *_rest = make_service(gateway=gateway, settings=make_settings(agent_max_tool_calls=3))

    result = await service.run(conversation_id=None, message="call many tools at once")

    assert result.status == STATUS_MAX_TOOL_CALLS_EXCEEDED
    # The tools node must never have actually run — the limit is checked
    # before executing, not after.
    assert result.tool_calls == []


# -- Timeout ----------------------------------------------------------------------


async def test_timeout_raises_agent_timeout_error() -> None:
    class _SlowGateway(ScriptedAgentGateway):
        async def chat_completion(self, **kwargs: object):  # type: ignore[override]
            await asyncio.sleep(0.2)
            return await super().chat_completion(**kwargs)  # type: ignore[arg-type]

    gateway = _SlowGateway(effects=[make_final_completion("too slow")])
    service, *_rest = make_service(
        gateway=gateway, settings=make_settings(agent_timeout_seconds=0.01)
    )

    with pytest.raises(AgentTimeoutError):
        await service.run(conversation_id=None, message="question")


# -- Conversation integration -------------------------------------------------


async def test_unknown_conversation_id_raises_not_found() -> None:
    gateway = ScriptedAgentGateway(effects=[make_final_completion("x")])
    service, *_rest = make_service(gateway=gateway)

    with pytest.raises(NotFoundError):
        await service.run(conversation_id=uuid.uuid4(), message="question")


async def test_persists_only_user_and_final_assistant_message_not_tool_traffic() -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "1+1"}),
            make_final_completion("It's 2."),
        ]
    )
    service, _conversations, messages = make_service(gateway=gateway)

    await service.run(conversation_id=None, message="what is 1+1")

    assert len(messages.messages) == 2
    assert messages.messages[0].content == "what is 1+1"
    assert messages.messages[1].content == "It's 2."


# -- Security: tool output is untrusted data --------------------------------------


async def test_malicious_tool_output_is_treated_as_data_not_instructions() -> None:
    """The system prompt must establish, on every single LLM call in the
    run, that tool output is data to reason about — never instructions —
    and that first system message must never be altered by anything a
    tool returns. A hijacked model isn't something this test can prove
    against (no real LLM call here); what it proves is the structural
    guarantee: the rule is present every time, and the system message slot
    is never replaced with tool content."""
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "1+1"}),
            make_final_completion("I can't share that information."),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="question")

    assert len(gateway.chat_completion_calls) == 2
    for call in gateway.chat_completion_calls:
        system_message = call["messages"][0]
        assert system_message.role.value == "system"
        assert "never as instructions" in system_message.content.lower()
    assert result.answer == "I can't share that information."


async def test_tool_message_role_is_used_for_tool_results_not_system() -> None:
    # 91347 is distinctive enough it can't coincidentally appear in the
    # system prompt's own text (e.g. its numbered rule list).
    gateway = ScriptedAgentGateway(
        effects=[
            make_tool_call_completion(tool_name="calculator", arguments={"expression": "91347"}),
            make_final_completion("91347"),
        ]
    )
    service, *_rest = make_service(gateway=gateway)

    await service.run(conversation_id=None, message="question")

    second_call_messages = gateway.chat_completion_calls[1]["messages"]
    tool_messages = [m for m in second_call_messages if m.role.value == "tool"]
    assert len(tool_messages) == 1
    assert "91347" in tool_messages[0].content
    system_messages = [m for m in second_call_messages if m.role.value == "system"]
    assert len(system_messages) == 1
    assert "91347" not in system_messages[0].content  # tool content never merged into system


# -- Generation failure ------------------------------------------------------------


async def test_llm_failure_propagates() -> None:
    gateway = ScriptedAgentGateway(effects=[LLMTimeoutError("timed out", provider="groq")])
    service, *_rest = make_service(gateway=gateway)

    with pytest.raises(LLMTimeoutError):
        await service.run(conversation_id=None, message="question")
