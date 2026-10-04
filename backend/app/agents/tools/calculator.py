"""A safe arithmetic tool — no `eval`/`exec`, ever.

`expression` is parsed with Python's `ast` module into a syntax tree, then
walked by `_evaluate`, which only recognizes a small, explicit allowlist of
node types. Anything else — a name, an attribute access, a function call, a
subscript, a comprehension, an import, a string, a lambda — raises
`UnsupportedExpressionError` before any evaluation happens. This is the
standard safe-arithmetic-via-AST pattern: the tree is data to interpret
ourselves, never code Python executes on our behalf.

Supported: `+ - * / // % **` (binary), unary `+`/`-`, parentheses, and
int/float numeric literals. Nothing else — no variables, no function calls,
no string/boolean/comparison operators.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from pydantic import BaseModel, Field

from app.agents.tools.base import ToolDefinition, ToolResult

# Deliberately excludes `@` (matrix multiply, meaningless for scalars) and
# bitwise operators (not arithmetic a business question would ask for).
_BINARY_OPERATORS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Computational-DoS guards: an AST walk prevents code injection, but a
# "legitimate" expression like `99999 ** 99999` can still hang the process
# or exhaust memory on an arbitrarily large result. These bounds are
# generous for any real business arithmetic (the brief's own examples are
# all well under 10) while making a pathological exponent a validation
# error instead of a resource exhaustion incident.
_MAX_OPERAND_MAGNITUDE = 1_000_000_000
_MAX_EXPONENT_MAGNITUDE = 100
_MAX_EXPRESSION_LENGTH = 200


class CalculatorError(Exception):
    """Base class for calculator-specific failures — never lets a raw
    `SyntaxError`/`ZeroDivisionError`/`OverflowError` escape to the caller
    as an unstructured crash."""


class UnsupportedExpressionError(CalculatorError):
    pass


class CalculatorArgs(BaseModel):
    expression: str = Field(
        max_length=_MAX_EXPRESSION_LENGTH,
        description=(
            "An arithmetic expression using +, -, *, /, //, %, **, parentheses, "
            "and number literals only — e.g. '250 * 0.18' or '(1000 / 12) + 50'."
        ),
    )


def evaluate_expression(expression: str) -> float:
    """Parses and evaluates `expression`. Raises `CalculatorError` (never a
    raw Python exception) for anything disallowed or pathological."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsupportedExpressionError(f"'{expression}' is not a valid expression") from exc
    return _evaluate(tree.body)


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise UnsupportedExpressionError("Only numeric literals are allowed")
        _check_operand_magnitude(node.value)
        return node.value

    if isinstance(node, ast.BinOp):
        operator_fn = _BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise UnsupportedExpressionError(f"Unsupported operator: {type(node.op).__name__}")
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT_MAGNITUDE:
            raise UnsupportedExpressionError(
                f"Exponent magnitude exceeds the allowed limit ({_MAX_EXPONENT_MAGNITUDE})"
            )
        if isinstance(node.op, ast.Div | ast.FloorDiv | ast.Mod) and right == 0:
            raise CalculatorError("Division by zero")
        try:
            result = operator_fn(left, right)
        except OverflowError as exc:
            raise CalculatorError("The result is too large to represent") from exc
        _check_operand_magnitude(result)
        return result

    if isinstance(node, ast.UnaryOp):
        operator_fn = _UNARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise UnsupportedExpressionError(f"Unsupported operator: {type(node.op).__name__}")
        return operator_fn(_evaluate(node.operand))

    raise UnsupportedExpressionError(f"Unsupported expression element: {type(node).__name__}")


def _check_operand_magnitude(value: float) -> None:
    if abs(value) > _MAX_OPERAND_MAGNITUDE:
        raise UnsupportedExpressionError(
            f"Operand magnitude exceeds the allowed limit ({_MAX_OPERAND_MAGNITUDE})"
        )


async def _execute(args: BaseModel) -> ToolResult:
    assert isinstance(args, CalculatorArgs)
    try:
        result = evaluate_expression(args.expression)
    except CalculatorError as exc:
        return ToolResult(success=False, error=str(exc), error_code="validation_error")
    return ToolResult(success=True, data={"expression": args.expression, "result": result})


CALCULATOR_TOOL = ToolDefinition(
    name="calculator",
    description=(
        "Evaluate a basic arithmetic expression (+, -, *, /, //, %, **, parentheses). "
        "Use this for any numeric calculation needed to answer a question — never "
        "compute arithmetic yourself in prose."
    ),
    args_schema=CalculatorArgs,
    executor=_execute,
)
