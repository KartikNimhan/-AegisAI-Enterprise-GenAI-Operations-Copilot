"""History window: bounded replay, whole messages only, starts on a user turn."""

from __future__ import annotations

from app.config import Settings
from app.domain.enums.message_role import MessageRole
from app.prompts.builder import PromptBuilder
from app.prompts.history import HistoryLimits, select_recent_history
from tests.unit.prompts.test_builder import make_message

U, A = MessageRole.USER, MessageRole.ASSISTANT


def turns(count: int, size: int = 10):
    out = []
    for i in range(count):
        out.append(make_message(U, f"q{i}".ljust(size, "x")))
        out.append(make_message(A, f"a{i}".ljust(size, "x")))
    return out


def test_short_history_is_unchanged() -> None:
    history = turns(3)
    assert select_recent_history(history) == history


def test_message_count_limit_keeps_newest_and_order() -> None:
    history = turns(10)
    chosen = select_recent_history(history, HistoryLimits(max_messages=4, max_chars=10_000))
    assert chosen == history[-4:]


def test_window_never_starts_with_an_assistant_reply() -> None:
    history = turns(10)
    chosen = select_recent_history(history, HistoryLimits(max_messages=5, max_chars=10_000))
    assert chosen[0].role == U
    assert chosen == history[-4:]


def test_char_budget_drops_whole_old_messages_without_gaps() -> None:
    history = [
        make_message(U, "u" * 5),
        make_message(A, "a" * 5000),
        make_message(U, "q" * 5),
        make_message(A, "r" * 5),
    ]
    chosen = select_recent_history(history, HistoryLimits(max_messages=40, max_chars=100))
    assert [m.content[0] for m in chosen] == ["q", "r"]


def test_empty_history_and_total_budget_miss() -> None:
    assert select_recent_history([]) == []
    only_big = [make_message(U, "x" * 500), make_message(A, "y" * 500)]
    assert select_recent_history(only_big, HistoryLimits(max_messages=40, max_chars=100)) == []


def test_prompt_builder_applies_the_window_and_keeps_current_message() -> None:
    builder = PromptBuilder(history_limits=HistoryLimits(max_messages=2, max_chars=1000))
    result = builder.build(history=turns(5), user_message="now")
    assert [m.content[:2] for m in result[1:]] == ["q4", "a4", "no"]


def test_limits_come_from_settings() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        debug=False,
        chat_history_max_messages=6,
        chat_history_max_chars=2000,
    )
    assert HistoryLimits.from_settings(settings) == HistoryLimits(6, 2000)
