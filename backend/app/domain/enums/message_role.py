"""The role of a persisted conversation message."""

from enum import StrEnum


class MessageRole(StrEnum):
    """Mirrors `app.llm.schemas.ChatRole`'s values intentionally.

    Kept as a separate type because `domain/` must not depend on `llm/`
    (the dependency direction is `llm` -> ... -> `domain`, never the
    reverse). `app.prompts.builder.PromptBuilder` is the one place that
    bridges the two when assembling a prompt from persisted history.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
