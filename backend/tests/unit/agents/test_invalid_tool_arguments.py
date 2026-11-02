"""A model that emits unusable tool arguments gets a controlled error, never a crashed run."""

from __future__ import annotations

import pytest

from app.agents.schemas import STATUS_COMPLETED
from app.llm.schemas import CompletionResponse, TokenUsage, ToolCall

from .doubles import ScriptedAgentGateway, make_final_completion
from .test_agent_service import make_service


def raw_call(arguments: str, call_id: str = "call_1") -> CompletionResponse:
    return CompletionResponse(
        content="",
        model="test-model",
        provider="test",
        finish_reason="tool_calls",
        usage=TokenUsage(),
        tool_calls=[ToolCall(id=call_id, name="calculator", arguments=arguments)],
    )


BAD_ARGUMENTS = ["{not json", "[1, 2]", '"just a string"', "42", "null"]


@pytest.mark.parametrize("arguments", BAD_ARGUMENTS)
async def test_run_survives_non_object_or_non_json_arguments(arguments: str) -> None:
    gateway = ScriptedAgentGateway(effects=[raw_call(arguments), make_final_completion("done")])
    service, *_ = await make_service(gateway=gateway)

    result = await service.run(conversation_id=None, message="question")

    assert result.status == STATUS_COMPLETED
    assert result.answer == "done"
    assert result.tool_calls[0].failure_count == 1


async def test_the_model_is_told_the_arguments_were_invalid_and_the_tool_did_not_run() -> None:
    gateway = ScriptedAgentGateway(effects=[raw_call("{oops"), make_final_completion("done")])
    service, *_ = await make_service(gateway=gateway)

    await service.run(conversation_id=None, message="question")

    second_call_messages = gateway.chat_completion_calls[1]["messages"]
    tool_reply = next(m for m in second_call_messages if m.role.value == "tool")
    assert "not a valid JSON object" in tool_reply.content
    assert '"success": false' in tool_reply.content


async def test_streaming_survives_invalid_arguments() -> None:
    gateway = ScriptedAgentGateway(effects=[raw_call("{oops"), make_final_completion("done")])
    service, *_ = await make_service(gateway=gateway)

    events = [event async for _id, event in service.run_stream(conversation_id=None, message="q")]

    names = [e.event for e in events]
    assert names[-1] == "completed"
    assert "tool_started" in names and "tool_completed" in names


async def test_unexpected_exceptions_are_still_raised_not_swallowed() -> None:
    gateway = ScriptedAgentGateway(effects=[RuntimeError("provider bug")])
    service, *_ = await make_service(gateway=gateway)

    with pytest.raises(RuntimeError, match="provider bug"):
        await service.run(conversation_id=None, message="question")
