"""Memory failures. Each carries a message that is safe to show the caller (and the model)."""

from __future__ import annotations


class AgentMemoryError(Exception):
    """Base class for memory errors."""


class MemoryValidationError(AgentMemoryError):
    """The note is empty, too long or contains control characters."""


class MemoryLimitError(AgentMemoryError):
    """A bound was reached: notes per user, or writes per agent run."""
