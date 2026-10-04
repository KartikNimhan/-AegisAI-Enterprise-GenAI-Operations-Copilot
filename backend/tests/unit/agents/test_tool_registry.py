"""Unit tests for ToolRegistry: registration, duplicates, unknown tools,
and the schema-validation step of execution."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.agents.tools.base import ToolDefinition, ToolRegistry, ToolResult


class _EchoArgs(BaseModel):
    text: str
    count: int = 1


async def _echo(args: BaseModel) -> ToolResult:
    assert isinstance(args, _EchoArgs)
    return ToolResult(success=True, data={"echoed": args.text * args.count})


def make_echo_tool(name: str = "echo") -> ToolDefinition:
    return ToolDefinition(
        name=name, description="Echoes text.", args_schema=_EchoArgs, executor=_echo
    )


def test_register_and_list_tools() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    assert [t.name for t in registry.list_tools()] == ["echo"]
    assert registry.get("echo") is not None


def test_duplicate_tool_name_is_rejected() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_echo_tool())


def test_get_unknown_tool_returns_none() -> None:
    registry = ToolRegistry()
    assert registry.get("does_not_exist") is None


def test_to_tool_specs_derives_json_schema_from_args_schema() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    specs = registry.to_tool_specs()

    assert len(specs) == 1
    assert specs[0].name == "echo"
    assert "text" in specs[0].parameters["properties"]
    assert "count" in specs[0].parameters["properties"]


async def test_execute_unknown_tool_returns_not_found_result() -> None:
    registry = ToolRegistry()

    result = await registry.execute("does_not_exist", "{}")

    assert result.success is False
    assert result.error_code == "not_found"


async def test_execute_with_invalid_json_arguments_returns_validation_error() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    result = await registry.execute("echo", "{not valid json")

    assert result.success is False
    assert result.error_code == "validation_error"


async def test_execute_with_schema_invalid_arguments_returns_validation_error() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    # "count" must be an int; this should fail Pydantic validation.
    result = await registry.execute("echo", json.dumps({"text": "hi", "count": "not-a-number"}))

    assert result.success is False
    assert result.error_code == "validation_error"


async def test_execute_with_missing_required_argument_returns_validation_error() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    result = await registry.execute("echo", json.dumps({}))

    assert result.success is False
    assert result.error_code == "validation_error"


async def test_execute_valid_arguments_calls_the_executor() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())

    result = await registry.execute("echo", json.dumps({"text": "ab", "count": 3}))

    assert result.success is True
    assert result.data == {"echoed": "ababab"}


async def test_execute_never_raises_when_executor_throws() -> None:
    async def _broken(args: BaseModel) -> ToolResult:
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="broken", description="always fails", args_schema=_EchoArgs, executor=_broken
        )
    )

    result = await registry.execute("broken", json.dumps({"text": "x"}))

    assert result.success is False
    assert result.error_code == "internal_error"
    assert "boom" not in (result.error or "")  # no raw exception text leaks


def test_tool_result_to_json_is_structured() -> None:
    result = ToolResult(success=True, data={"a": 1})
    payload = json.loads(result.to_json())
    assert payload == {"success": True, "data": {"a": 1}, "error": None}
