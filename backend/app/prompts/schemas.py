"""Schemas for prompt templates themselves (identity + versioning).

Not to be confused with `app.llm.schemas.ChatMessage` — that's the
provider-neutral message shape sent to the LLM gateway. A `PromptTemplate`
is metadata about *where a piece of prompt text came from*, so that which
version produced a given response can be identified later (useful once
evaluation/observability milestones land).
"""

from __future__ import annotations

from pydantic import BaseModel


class PromptTemplate(BaseModel):
    id: str
    version: int
    text: str
