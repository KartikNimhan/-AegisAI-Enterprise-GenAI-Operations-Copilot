"""The single entry point the rest of the application uses for LLM calls.

`LLMGateway` resolves a `ModelRole` to a configured model name, delegates to
an `LLMProvider`, standardizes responses, retries transient failures with
backoff, and logs structured (never sensitive) metadata around every call.
No caller outside `app.llm` should import a provider or its SDK directly.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from typing import TypeVar

import structlog

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.exceptions import (
    LLMError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import ChatMessage, CompletionResponse, ModelRole, StreamChunk

logger = structlog.get_logger(__name__)

_RETRYABLE_EXCEPTIONS = (LLMRateLimitError, LLMTimeoutError, LLMProviderUnavailableError)
_MAX_BACKOFF_SECONDS = 8.0

T = TypeVar("T")


class LLMGateway:
    def __init__(self, settings: Settings, provider: LLMProvider | None = None) -> None:
        self._settings = settings
        self._provider = provider or GroqProvider(settings)
        self._model_by_role: dict[ModelRole, str] = {
            ModelRole.PRIMARY: settings.primary_llm_model,
            ModelRole.FAST: settings.fast_llm_model,
            ModelRole.SAFETY: settings.safety_llm_model,
        }

    def resolve_model(self, role: ModelRole) -> str:
        return self._model_by_role[role]

    def model_metadata(self) -> dict[str, str]:
        """Exposes the active provider and the model configured for each role."""
        metadata = {role.value: model for role, model in self._model_by_role.items()}
        metadata["provider"] = self._provider.name
        return metadata

    async def chat_completion(
        self,
        *,
        model_role: ModelRole,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, object] | None = None,
    ) -> CompletionResponse:
        model = self.resolve_model(model_role)

        async def call() -> CompletionResponse:
            return await self._provider.complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

        return await self._with_retries(
            model_role=model_role, model=model, operation="chat_completion", call=call
        )

    async def stream_chat_completion(
        self,
        *,
        model_role: ModelRole,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streams normalized chunks. Not retried: partial output may already
        have reached the caller by the time a mid-stream failure occurs."""
        model = self.resolve_model(model_role)
        start = time.perf_counter()
        logger.info(
            "llm_stream_started",
            provider=self._provider.name,
            model=model,
            model_role=model_role.value,
        )
        try:
            async for chunk in self._provider.stream_complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                yield chunk
        except LLMError as exc:
            logger.warning(
                "llm_stream_failed",
                provider=self._provider.name,
                model=model,
                model_role=model_role.value,
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        else:
            logger.info(
                "llm_stream_completed",
                provider=self._provider.name,
                model=model,
                model_role=model_role.value,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )

    async def _with_retries(
        self,
        *,
        model_role: ModelRole,
        model: str,
        operation: str,
        call: Callable[[], Awaitable[T]],
    ) -> T:
        max_attempts = self._settings.llm_max_retries + 1
        attempt = 0
        while True:
            attempt += 1
            start = time.perf_counter()
            try:
                result = await call()
            except _RETRYABLE_EXCEPTIONS as exc:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                if attempt >= max_attempts:
                    logger.warning(
                        "llm_request_failed",
                        provider=self._provider.name,
                        model=model,
                        model_role=model_role.value,
                        operation=operation,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        duration_ms=duration_ms,
                    )
                    raise
                delay = _backoff_delay(attempt, exc)
                logger.info(
                    "llm_request_retry",
                    provider=self._provider.name,
                    model=model,
                    model_role=model_role.value,
                    operation=operation,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    delay_seconds=delay,
                    duration_ms=duration_ms,
                )
                await asyncio.sleep(delay)
                continue
            except LLMError as exc:
                logger.warning(
                    "llm_request_failed",
                    provider=self._provider.name,
                    model=model,
                    model_role=model_role.value,
                    operation=operation,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                )
                raise
            else:
                logger.info(
                    "llm_request_succeeded",
                    provider=self._provider.name,
                    model=model,
                    model_role=model_role.value,
                    operation=operation,
                    attempt=attempt,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    **_usage_log_fields(result),
                )
                return result


def _usage_log_fields(result: object) -> dict[str, object]:
    usage = getattr(result, "usage", None)
    request_id = getattr(result, "request_id", None)
    if usage is None:
        return {"request_id": request_id}
    return {
        "request_id": request_id,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _backoff_delay(attempt: int, exc: Exception) -> float:
    base_delay = min(0.5 * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        return max(base_delay, float(retry_after))
    return base_delay


@lru_cache
def get_llm_gateway() -> LLMGateway:
    return LLMGateway(get_settings())
