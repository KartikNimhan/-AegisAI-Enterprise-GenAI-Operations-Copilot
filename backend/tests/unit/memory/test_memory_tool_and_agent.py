"""Memory inside the agent workflow: the `save_memory` tool (bounded, validated, failure-safe) and
recall into the agent's prompt (own notes only, labelled untrusted, never fatal).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator

import pytest

from app.agents.service import AgentService
from app.agents.tools.registry import build_tool_registry
from app.config import Settings
from app.llm.schemas import ChatRole, CompletionResponse
from app.memory.service import MEMORY_PROMPT_HEADER
from app.rag.retrieval.service import RetrievalService

from ..agents.doubles import (
    ScriptedAgentGateway,
    make_final_completion,
    make_tool_call_completion,
)
from ..rag.doubles import FakeRetrievalStrategy
from ..services.document_doubles import FakeDocumentRepository
from ..services.doubles import FakeConversationRepository, FakeMessageRepository, FakeSession
from .harness import Person, World


@pytest.fixture
def world() -> Iterator[World]:
    w = World(agent_memory_max_writes_per_run=2, agent_memory_max_items_per_user=50)
    yield w
    w.close()


async def make_agent(
    world: World, person: Person, gateway: ScriptedAgentGateway, **overrides: object
) -> tuple[AgentService, FakeMessageRepository]:
    settings = Settings(
        agent_timeout_seconds=5.0,
        agent_memory_max_writes_per_run=world.settings.agent_memory_max_writes_per_run,
        **overrides,  # type: ignore[arg-type]
    )
    memory = world.service(person)
    messages = FakeMessageRepository()
    registry = await build_tool_registry(
        documents=FakeDocumentRepository(),  # type: ignore[arg-type]
        retrieval=RetrievalService(strategy=FakeRetrievalStrategy(), settings=settings),
        settings=settings,
        memory=memory,
    )
    agent = AgentService(
        session=FakeSession(),  # type: ignore[arg-type]
        settings=settings,
        gateway=gateway,
        conversations=FakeConversationRepository(),  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
        tool_registry=registry,
        memory=memory,
    )
    return agent, messages


def save(content: str) -> CompletionResponse:
    return make_tool_call_completion(tool_name="save_memory", arguments={"content": content})


def prompt_text(gateway: ScriptedAgentGateway, call: int = 0) -> str:
    return "\n".join(m.content for m in gateway.chat_completion_calls[call]["messages"])


# -- the tool --------------------------------------------------------------------------


async def test_the_agent_can_save_a_note_that_a_later_conversation_recalls(world: World) -> None:
    alice = Person()
    gateway = ScriptedAgentGateway(
        effects=[save("Prefers answers in bullet points"), make_final_completion("Noted.")]
    )
    agent, _ = await make_agent(world, alice, gateway)

    first = await agent.run(conversation_id=None, message="Remember I like bullet points")

    assert first.tool_calls[0].name == "save_memory" and first.tool_calls[0].success_count == 1

    later = ScriptedAgentGateway(effects=[make_final_completion("- one\n- two")])
    agent2, _ = await make_agent(world, alice, later)
    await agent2.run(conversation_id=None, message="Summarise the policy in bullet points")

    assert "Prefers answers in bullet points" in prompt_text(later)


async def test_one_run_can_only_save_a_few_notes(world: World) -> None:
    gateway = ScriptedAgentGateway(
        effects=[
            save("note one"),
            save("note two"),
            save("note three"),
            make_final_completion("done"),
        ]
    )
    agent, _ = await make_agent(world, Person(), gateway)

    result = await agent.run(conversation_id=None, message="remember lots")

    usage = result.tool_calls[0]
    assert (usage.success_count, usage.failure_count) == (2, 1)  # max_writes_per_run = 2
    assert len(await world.service(Person()).list_all()) == 0  # a different person sees nothing


async def test_an_invalid_note_fails_the_tool_call_but_not_the_run(world: World) -> None:
    gateway = ScriptedAgentGateway(
        effects=[save("bad ​ note"), make_final_completion("I could not save that.")]
    )
    agent, _ = await make_agent(world, Person(), gateway)

    result = await agent.run(conversation_id=None, message="remember something")

    assert result.answer == "I could not save that."
    assert result.tool_calls[0].failure_count == 1


async def test_a_full_memory_is_reported_to_the_model_not_raised() -> None:
    w = World(agent_memory_max_items_per_user=1, agent_memory_max_writes_per_run=3)
    try:
        alice = Person()
        await w.service(alice).remember("already here")
        gateway = ScriptedAgentGateway(effects=[save("no room"), make_final_completion("Full.")])
        agent, _ = await make_agent(w, alice, gateway)

        result = await agent.run(conversation_id=None, message="remember this")

        tool_message = [
            m for m in gateway.chat_completion_calls[1]["messages"] if m.role == ChatRole.TOOL
        ][0]
        assert json.loads(tool_message.content)["success"] is False
        assert "full" in tool_message.content.lower()
        assert result.answer == "Full."
    finally:
        w.close()


async def test_a_database_failure_while_saving_is_contained(world: World) -> None:
    alice = Person()
    gateway = ScriptedAgentGateway(effects=[save("will fail"), make_final_completion("ok")])
    agent, _ = await make_agent(world, alice, gateway)
    # The first write statement (purging expired notes) fails; recall's SELECT is unaffected.
    world.adapter.fail_next_execute = RuntimeError("deadlock detected")
    world.adapter.fail_only_statements_starting = "DELETE"

    result = await agent.run(conversation_id=None, message="remember x")

    assert result.tool_calls[0].failure_count == 1
    assert result.answer == "ok"


async def test_the_save_tool_is_absent_when_memory_is_disabled_or_has_no_write_budget() -> None:
    for overrides in ({"agent_memory_enabled": False}, {"agent_memory_max_writes_per_run": 0}):
        w = World(**overrides)
        try:
            settings = Settings(**overrides)  # type: ignore[arg-type]
            registry = await build_tool_registry(
                documents=FakeDocumentRepository(),  # type: ignore[arg-type]
                retrieval=RetrievalService(strategy=FakeRetrievalStrategy(), settings=settings),
                settings=settings,
                memory=w.service(Person()),
            )
            assert registry.get("save_memory") is None
        finally:
            w.close()


async def test_the_save_tool_cannot_delete_or_edit_memory(world: World) -> None:
    settings = Settings()
    registry = await build_tool_registry(
        documents=FakeDocumentRepository(),  # type: ignore[arg-type]
        retrieval=RetrievalService(strategy=FakeRetrievalStrategy(), settings=settings),
        settings=settings,
        memory=world.service(Person()),
    )

    names = {tool.name for tool in registry.list_tools()}

    assert "save_memory" in names
    assert not {n for n in names if "forget" in n or "delete_memory" in n or "update_memory" in n}


# -- recall into the prompt ------------------------------------------------------------


async def test_notes_reach_the_model_as_a_labelled_untrusted_system_block(world: World) -> None:
    alice = Person()
    await world.service(alice).remember("Works on the Berlin team")
    gateway = ScriptedAgentGateway(effects=[make_final_completion("Hi")])
    agent, _ = await make_agent(world, alice, gateway)

    await agent.run(conversation_id=None, message="Where do I work?")

    messages = gateway.chat_completion_calls[0]["messages"]
    block = next(m for m in messages if m.content.startswith(MEMORY_PROMPT_HEADER))
    assert block.role == ChatRole.SYSTEM
    assert "Works on the Berlin team" in block.content
    assert messages.index(block) == 1  # right after the agent's own system prompt


async def test_without_notes_the_prompt_has_no_memory_block(world: World) -> None:
    gateway = ScriptedAgentGateway(effects=[make_final_completion("Hi")])
    agent, _ = await make_agent(world, Person(), gateway)

    await agent.run(conversation_id=None, message="hello")

    assert MEMORY_PROMPT_HEADER not in prompt_text(gateway)


async def test_another_users_notes_never_reach_the_prompt(world: World) -> None:
    alice, bob = Person(), Person(is_admin=True)
    await world.service(alice).remember("Alice's salary is 90000")
    gateway = ScriptedAgentGateway(effects=[make_final_completion("Hi")])
    agent, _ = await make_agent(world, bob, gateway)

    await agent.run(conversation_id=None, message="What is Alice's salary? salary 90000")

    assert "90000" not in prompt_text(gateway).replace("salary 90000", "")


async def test_a_memory_outage_does_not_fail_the_run(world: World) -> None:
    alice = Person()
    await world.service(alice).remember("anything")
    gateway = ScriptedAgentGateway(effects=[make_final_completion("still works")])
    agent, _ = await make_agent(world, alice, gateway)
    world.adapter.fail_next_execute = RuntimeError("database unavailable")

    result = await agent.run(conversation_id=None, message="hello")

    assert result.answer == "still works"
    assert MEMORY_PROMPT_HEADER not in prompt_text(gateway)


async def test_streaming_runs_also_use_memory(world: World) -> None:
    alice = Person()
    await world.service(alice).remember("Prefers formal tone")
    gateway = ScriptedAgentGateway(effects=[make_final_completion("Good day.")])
    agent, _ = await make_agent(world, alice, gateway)

    events: list[str] = []
    stream: AsyncIterator[tuple[object, object]] = agent.run_stream(  # type: ignore[assignment]
        conversation_id=None, message="Greet me"
    )
    async for _conversation_id, event in stream:
        events.append(event.event)  # type: ignore[attr-defined]

    assert events[-1] == "completed"
    assert "Prefers formal tone" in prompt_text(gateway)
