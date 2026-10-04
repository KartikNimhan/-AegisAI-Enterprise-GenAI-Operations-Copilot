"""The application-level tool abstraction.

`ToolDefinition` is deliberately richer than `app.llm.schemas.ToolSpec`
(which is only what gets sent to the LLM provider): it also carries the
Pydantic model that validates the model's generated arguments and the
actual async function that executes the tool. The LLM only ever sees a
`ToolSpec` (name/description/JSON-schema parameters) derived from a
registered `ToolDefinition` — it can never reach a Python callable
directly, and only a name it was explicitly told about can ever be
executed (see `ToolRegistry.execute`).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

from app.llm.schemas import ToolSpec

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """The structured contract every tool execution returns — never an
    arbitrary string, and never a raw exception/stack trace.

    `error_code` lets the agent (and `AgentService`'s retry policy, see
    ADR 008) distinguish failure classes without parsing `error` text:
    `"validation_error"` (bad arguments — permanent, do not retry the same
    call), `"not_found"` (permanent), `"permission_denied"` (permanent,
    reserved for future authorization checks), `"transient_error"`
    (worth a different call/strategy), `"internal_error"` (an unexpected
    failure inside the tool, already logged, never a raw traceback).
    """

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None

    def to_json(self) -> str:
        """The JSON string sent back to the model as a TOOL message's
        content — the model must be able to distinguish success from
        failure structurally, not by guessing at free text."""
        return json.dumps(
            {"success": self.success, "data": self.data, "error": self.error},
            default=str,
        )


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_schema: type[BaseModel]
    executor: Callable[[BaseModel], Awaitable[ToolResult]]
    # Human-in-the-loop foundation (not implemented this milestone — see
    # ADR 008, "Human-in-the-loop foundation"): a future sensitive tool
    # would set this True, and the graph would pause before `executor` runs
    # rather than calling it immediately. All three Milestone 6 tools are
    # read-only/side-effect-free, so this is always False here.
    requires_approval: bool = False

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.args_schema.model_json_schema(),
        )


class ToolRegistry:
    """Owns the explicit allowlist of tools the agent may call. Only a
    name registered here can ever execute — there is no path from a model
    output to an arbitrary Python callable."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def to_tool_specs(self) -> list[ToolSpec]:
        return [tool.to_spec() for tool in self._tools.values()]

    async def execute(self, name: str, raw_arguments: str) -> ToolResult:
        """LLM-generated arguments -> schema validation -> execution
        (business/authorization validation happens inside each tool's
        `executor`, which is the only place that knows what's valid for
        that specific tool — e.g. "does this document exist").

        Never raises: a tool crashing must not take down the agent run,
        so any unexpected exception becomes a structured `internal_error`
        result instead, with the real exception only in the server log.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False, error=f"Unknown tool: {name!r}", error_code="not_found"
            )

        try:
            parsed_arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error="Tool arguments were not valid JSON",
                error_code="validation_error",
            )

        try:
            validated_args = tool.args_schema.model_validate(parsed_arguments)
        except ValidationError as exc:
            return ToolResult(
                success=False,
                error=f"Invalid arguments for tool {name!r}: {exc.error_count()} error(s)",
                error_code="validation_error",
            )

        try:
            return await tool.executor(validated_args)
        except Exception:
            logger.exception("tool_execution_failed", tool_name=name)
            return ToolResult(
                success=False,
                error="The tool failed to execute",
                error_code="internal_error",
            )
