"""Typed, provider-neutral exceptions for the LLM gateway.

Raw provider SDK exceptions (e.g. from the `groq` package) must never cross
the `app.llm.providers` boundary — `providers/groq.py` translates every
exception it can raise into one of these before it reaches the gateway or
the API layer.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM gateway errors."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.request_id = request_id
        super().__init__(message)


class LLMAuthenticationError(LLMError):
    """Credentials are missing, invalid, or not authorized."""


class LLMRateLimitError(LLMError):
    """The provider rejected the request due to rate limiting."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, provider=provider, request_id=request_id)


class LLMTimeoutError(LLMError):
    """The request to the provider timed out."""


class LLMProviderUnavailableError(LLMError):
    """The provider is unreachable or returned a server-side (5xx) error."""


class LLMInvalidRequestError(LLMError):
    """The request was rejected by the provider as invalid."""


class LLMProviderError(LLMError):
    """An unexpected, unmapped provider error occurred."""
