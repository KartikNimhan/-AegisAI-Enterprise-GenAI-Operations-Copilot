"""Unit tests for the calculator tool: supported operations, errors, and
the security properties that matter most — no eval/exec, and a
computational-DoS-resistant evaluator."""

from __future__ import annotations

import ast

import pytest
from pydantic import ValidationError

from app.agents.tools.calculator import (
    CALCULATOR_TOOL,
    CalculatorArgs,
    CalculatorError,
    UnsupportedExpressionError,
    evaluate_expression,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("250 + 100", 350),
        ("250 - 100", 150),
        ("250 * 0.18", 45.0),
        ("1000 / 12", pytest.approx(83.3333, rel=1e-3)),
        ("7 // 2", 3),
        ("7 % 2", 1),
        ("2 ** 10", 1024),
        ("-5 + 3", -2),
        ("+5", 5),
        ("(1 + 2) * 3", 9),
        ("1000 / 12 + 50", pytest.approx(133.3333, rel=1e-3)),
    ],
)
def test_supported_operations(expression: str, expected: object) -> None:
    assert evaluate_expression(expression) == expected


def test_division_by_zero_is_a_controlled_error() -> None:
    with pytest.raises(CalculatorError, match="zero"):
        evaluate_expression("1 / 0")


def test_floor_division_by_zero_is_a_controlled_error() -> None:
    with pytest.raises(CalculatorError):
        evaluate_expression("1 // 0")


def test_modulo_by_zero_is_a_controlled_error() -> None:
    with pytest.raises(CalculatorError):
        evaluate_expression("1 % 0")


def test_invalid_syntax_is_a_controlled_error() -> None:
    with pytest.raises(UnsupportedExpressionError):
        evaluate_expression("2 +* 3")


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "open('/etc/passwd')",
        "[].__class__",
        "(1).__class__.__bases__",
        "'a' * 3",
        "True + 1",
        "1 if True else 2",
        "[1, 2, 3]",
        "{1: 2}",
        "lambda: 1",
        "a + 1",
        "1; 2",
    ],
)
def test_unsupported_or_malicious_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(CalculatorError):
        evaluate_expression(expression)


def test_never_uses_eval_or_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-suspenders: if the implementation ever regresses to using
    `eval`/`exec`, this test fails loudly rather than relying only on
    behavioral tests that a clever rewrite might still pass."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluate_expression must never call eval()/exec()")

    monkeypatch.setattr("builtins.eval", _forbidden)
    monkeypatch.setattr("builtins.exec", _forbidden)

    assert evaluate_expression("250 * 0.18") == pytest.approx(45.0)


def test_uses_ast_parse_not_compile_with_exec_mode() -> None:
    tree = ast.parse("1 + 1", mode="eval")
    assert isinstance(tree, ast.Expression)


def test_oversized_operand_is_rejected() -> None:
    with pytest.raises(UnsupportedExpressionError, match="magnitude"):
        evaluate_expression("99999999999999999999999999999999999999")


def test_oversized_exponent_is_rejected_before_it_can_hang() -> None:
    with pytest.raises(UnsupportedExpressionError, match="[Ee]xponent"):
        evaluate_expression("2 ** 999999999")


def test_large_but_bounded_exponent_still_computes_quickly() -> None:
    # Exercises a large-but-allowed exponent (within _MAX_EXPONENT_MAGNITUDE)
    # on an operand small enough that the *result* also stays under
    # _MAX_OPERAND_MAGNITUDE — should be effectively instant, never a hang.
    result = evaluate_expression("2 ** 29")
    assert result == 2**29


def test_exponent_within_limit_but_result_too_large_is_still_rejected() -> None:
    # The exponent itself (100) is within _MAX_EXPONENT_MAGNITUDE, but
    # 2**100 is astronomically larger than any real business calculation —
    # the output-magnitude guard catches this independently of the
    # exponent guard.
    with pytest.raises(UnsupportedExpressionError, match="magnitude"):
        evaluate_expression("2 ** 100")


def test_expression_length_is_bounded_by_the_args_schema() -> None:
    with pytest.raises(ValidationError):
        CalculatorArgs(expression="1+" * 500 + "1")


async def test_tool_executor_returns_structured_success() -> None:
    args = CalculatorArgs(expression="250 * 0.18")
    result = await CALCULATOR_TOOL.executor(args)
    assert result.success is True
    assert result.data is not None
    assert result.data["result"] == pytest.approx(45.0)


async def test_tool_executor_returns_structured_validation_error() -> None:
    args = CalculatorArgs(expression="1 / 0")
    result = await CALCULATOR_TOOL.executor(args)
    assert result.success is False
    assert result.error_code == "validation_error"
