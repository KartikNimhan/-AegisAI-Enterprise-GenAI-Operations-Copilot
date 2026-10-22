"""Input bounds shared by the API layer and the agents (see ADR 016).

Without a ceiling a single request could carry megabytes of text into a prompt: cost, latency, and
a context overflow that fails the whole turn. These are generous for real use (32,000 characters
is about 8,000 tokens) but finite. They are code constants, not settings: a request that exceeds
them is malformed, not a deployment choice.
"""

MAX_MESSAGE_CHARS = 32_000
MAX_TASK_ITEMS = 50  # document ids per document-agent task
MAX_EXPRESSION_CHARS = 500
MAX_EXPRESSIONS = 20
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_CHARS = 100_000
