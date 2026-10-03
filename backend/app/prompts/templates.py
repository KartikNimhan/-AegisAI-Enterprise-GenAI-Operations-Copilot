"""Prompt template definitions.

Add new templates here as new use cases appear (e.g. a safety-role prompt,
a future RAG prompt) — each gets its own `id` and starts at `version=1`.
Bump `version` (don't mutate `text` in place) when a template's wording
changes, so which version produced a given persisted response stays
identifiable.
"""

from app.prompts.schemas import PromptTemplate

AEGIS_CHAT_SYSTEM_PROMPT = PromptTemplate(
    id="aegis-chat-system",
    version=1,
    text=(
        "You are AegisAI, an enterprise GenAI operations copilot. "
        "Be concise, accurate, and professional. If you are not sure about "
        "something, say so rather than guessing. You do not have access to "
        "tools, documents, or external systems in this conversation — rely "
        "only on the conversation so far."
    ),
)
