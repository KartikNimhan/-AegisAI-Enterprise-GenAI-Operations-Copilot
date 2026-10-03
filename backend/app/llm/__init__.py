"""The LLM gateway: a provider-neutral abstraction over chat completion.

Application code must depend on `app.llm.gateway.LLMGateway` (or, more
commonly, `app.services.chat_service.ChatService`), never on a provider SDK.
Only Groq is implemented in this milestone — see `providers/groq.py` and
`docs/architecture/decisions/002-llm-gateway.md`.
"""
