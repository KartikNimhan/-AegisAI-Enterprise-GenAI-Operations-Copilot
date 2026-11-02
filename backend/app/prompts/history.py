"""Bounded conversation history for prompts.

Every turn used to replay the WHOLE persisted conversation into the prompt, so a long conversation
grew without limit: rising cost and latency, then a provider context-length error that failed every
later turn. History is now a window: the most recent messages that fit a message count and a
character budget (a cheap, provider-independent stand-in for a token budget). Older turns stay in
the database and in the conversation view; they just stop being replayed to the model. Nothing is
summarised or rewritten, and the current user message is never part of this budget.

See docs/architecture/decisions/016-input-bounds-and-history-limits.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.enums.message_role import MessageRole
from app.domain.models.message import Message

if TYPE_CHECKING:
    from app.config import Settings

DEFAULT_MAX_MESSAGES = 40
DEFAULT_MAX_CHARS = 24_000


@dataclass(frozen=True)
class HistoryLimits:
    max_messages: int = DEFAULT_MAX_MESSAGES
    max_chars: int = DEFAULT_MAX_CHARS

    @classmethod
    def from_settings(cls, settings: Settings) -> HistoryLimits:
        return cls(
            max_messages=settings.chat_history_max_messages,
            max_chars=settings.chat_history_max_chars,
        )


def select_recent_history(
    history: Sequence[Message], limits: HistoryLimits | None = None
) -> list[Message]:
    """The newest messages of `history` (chronological order kept) within both limits.

    A message is included only whole: the window stops at the first older message that would not
    fit, so a very large old message is dropped rather than truncated, and the window never has a
    gap. A window that would start with an assistant reply starts at the next user message instead,
    so the model always sees a question before its answer.
    """
    bounds = limits or HistoryLimits()
    chosen: list[Message] = []
    used = 0
    for message in reversed(history):
        if len(chosen) >= bounds.max_messages or used + len(message.content) > bounds.max_chars:
            break
        chosen.append(message)
        used += len(message.content)
    chosen.reverse()
    while chosen and chosen[0].role != MessageRole.USER:
        chosen.pop(0)
    return chosen
