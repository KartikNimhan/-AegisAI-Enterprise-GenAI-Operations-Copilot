"""Concrete LLMProvider implementations.

Only `groq.py` is implemented in this milestone. Each provider module is the
only place allowed to import its corresponding SDK — everything outside
`app.llm.providers` must go through `app.llm.base.LLMProvider` /
`app.llm.gateway.LLMGateway`.
"""
