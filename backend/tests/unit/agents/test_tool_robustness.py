"""Malformed input fails one item cleanly instead of aborting a whole task (AIGSEC-014).

Calculator arithmetic edge cases, the analyst's per-expression validation (and its limit now
being the calculator's), Agent Card validation, and token-usage coercion. All offline.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.a2a.analyst_agent import AnalystAgentService
from app.a2a.client import _validate_card
from app.a2a.exceptions import A2AInvalidCardError
from app.agents.tools.calculator import (
    CALCULATOR_TOOL,
    CalculatorArgs,
    CalculatorError,
    evaluate_expression,
)
from app.api.schemas.common import ExpressionText
from app.core.limits import MAX_EXPRESSION_CHARS
from app.multi_agent.adapters import _coerce_token_usage

# -- calculator -----------------------------------------------------------------------------


@pytest.mark.parametrize("expression", ["0 ** -1", "0 ** -2.5", "(1 - 1) ** -3", "1 / 0", "5 % 0"])
def test_division_by_zero_in_every_form_is_a_calculator_error(expression: str) -> None:
    with pytest.raises(CalculatorError, match="Division by zero"):
        evaluate_expression(expression)


@pytest.mark.parametrize(("expression", "expected"), [("2 ** -1", 0.5), ("10 ** -2", 0.01)])
def test_negative_exponents_of_a_non_zero_base_still_work(expression: str, expected: float) -> None:
    assert evaluate_expression(expression) == pytest.approx(expected)


def test_zero_to_a_positive_or_zero_power_still_works() -> None:
    assert evaluate_expression("0 ** 2") == 0
    assert evaluate_expression("0 ** 0") == 1


async def test_the_tool_answers_zero_to_a_negative_power_as_a_structured_error() -> None:
    result = await CALCULATOR_TOOL.executor(CalculatorArgs(expression="0 ** -1"))

    assert result.success is False
    assert result.error == "Division by zero"


def test_ordinary_calculations_are_unchanged() -> None:
    assert evaluate_expression("(2 + 3) * 4 - 6 / 3") == 18


# -- the analyst's expressions ------------------------------------------------------------------


def test_the_api_accepts_exactly_what_the_calculator_accepts() -> None:
    from pydantic import TypeAdapter

    adapter = TypeAdapter(ExpressionText)
    longest = "1+" * ((MAX_EXPRESSION_CHARS - 1) // 2) + "1"
    assert len(longest) <= MAX_EXPRESSION_CHARS
    adapter.validate_python(longest)
    CalculatorArgs(expression=longest)  # the calculator takes it too
    with pytest.raises(ValueError):
        adapter.validate_python("1" * (MAX_EXPRESSION_CHARS + 1))
    assert CalculatorArgs.model_fields["expression"].metadata[-1].max_length == MAX_EXPRESSION_CHARS


async def test_one_oversized_expression_fails_alone_and_the_others_are_evaluated() -> None:
    service = AnalystAgentService(gateway=None)  # type: ignore[arg-type] - no evidence, no LLM

    result = await service.analyze(
        question="",
        expressions=["2 + 2", "1" * (MAX_EXPRESSION_CHARS + 50), "0 ** -1"],
        evidence=[],
    )

    ok, too_long, zero = result.calculations
    assert (ok.success, ok.result) == (True, 4)
    assert (too_long.success, too_long.error) == (False, "The expression is empty or too long")
    assert len(too_long.expression) <= MAX_EXPRESSION_CHARS  # not echoed back in full
    assert (zero.success, zero.error) == (False, "Division by zero")
    assert result.status == "completed"  # the task itself still completes


# -- Agent Cards ------------------------------------------------------------------------------

_GOOD = {"name": "Agent", "skills": [{"id": "s"}], "supportedInterfaces": [{"url": "u"}]}


@pytest.mark.parametrize(
    "card",
    [
        ["not", "an", "object"],
        "a string",
        None,
        {**_GOOD, "skills": "s"},
        {**_GOOD, "skills": ["s"]},
        {**_GOOD, "skills": [{"id": "s"}, 3]},
    ],
)
def test_a_malformed_card_is_an_invalid_card_never_a_crash(card: Any) -> None:
    with pytest.raises(A2AInvalidCardError):
        _validate_card(card, expected_name="Agent", expected_skill_id="s")


def test_a_well_formed_card_still_passes() -> None:
    _validate_card(_GOOD, expected_name="Agent", expected_skill_id="s")


# -- token usage ------------------------------------------------------------------------------


def test_numeric_token_counts_are_restored_to_integers() -> None:
    assert _coerce_token_usage(
        {"input_tokens": 15.0, "output_tokens": 3, "total_tokens": None}
    ) == {
        "input_tokens": 15,
        "output_tokens": 3,
        "total_tokens": None,
    }


@pytest.mark.parametrize(
    "value", ["fifteen", "15", -1, float("inf"), float("nan"), {"nested": 1}, [1], True]
)
def test_a_malformed_token_count_is_unknown_not_an_error(value: Any) -> None:
    assert _coerce_token_usage({"input_tokens": value}) == {"input_tokens": None}


@pytest.mark.parametrize("raw", [None, "usage", [1, 2], 5])
def test_malformed_token_usage_as_a_whole_is_unknown(raw: Any) -> None:
    assert _coerce_token_usage(raw) is None
