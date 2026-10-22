"""What an agent memory records."""

from enum import StrEnum


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"


class MemorySource(StrEnum):
    """Who created the note: the agent through its `save_memory` tool, or the user directly."""

    AGENT = "agent"
    USER = "user"
