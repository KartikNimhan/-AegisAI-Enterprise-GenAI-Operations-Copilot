"""Prompt management: versioned templates + a builder that assembles the
provider-neutral message list sent to the LLM gateway.

No templating engine/framework is introduced — this is plain Python and
`str` text, kept small on purpose so it can later grow a system prompt per
use case (agent prompts, RAG prompts, evaluation prompts) without a rewrite.
"""
