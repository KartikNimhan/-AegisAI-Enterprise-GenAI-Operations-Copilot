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
    LLMOutputTruncatedError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import ChatMessage, CompletionResponse, ModelRole, StreamChunk, ToolSpec
from app.observability import metrics

logger = structlog.get_logger(__name__)

_RETRYABLE_EXCEPTIONS = (LLMRateLimitError, LLMTimeoutError, LLMProviderUnavailableError)
_MAX_BACKOFF_SECONDS = 8.0
# A provider asking us to wait longer than this (Retry-After) is not retried: sleeping would hold
# the request open for minutes. The error surfaces immediately instead.
_MAX_RETRY_WAIT_SECONDS = 20.0
# A reply cut off by the output limit before any text or tool call (e.g. a reasoning model that
# spent the whole budget on hidden reasoning) is a failure, not an empty answer.
_LENGTH_LIMIT = "length"
_NO_OUTPUT_MESSAGE = "The model reached its output limit before producing any text"

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
        tools: list[ToolSpec] | None = None,
    ) -> CompletionResponse:
        model = self.resolve_model(model_role)

        async def call() -> CompletionResponse:
            response = await self._provider.complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                tools=tools,
            )
            if _cut_off_without_output(response):
                # The tokens were still spent (and billed): count them before failing. Not
                # retryable, so `_with_retries` records it as an error and re-raises.
                metrics.record_llm_tokens(self._provider.name, model_role.value, response.usage)
                raise LLMOutputTruncatedError(
                    _NO_OUTPUT_MESSAGE, provider=self._provider.name, request_id=response.request_id
                )
            return response

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
        usage_recorded = False
        produced_text = False
        try:
            async for chunk in self._with_deadline(
                self._provider.stream_complete(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            ):
                if chunk.usage is not None and not usage_recorded:
                    # Providers report usage on the final chunk; observing it changes nothing
                    # about the chunk or the stream.
                    metrics.record_llm_tokens(self._provider.name, model_role.value, chunk.usage)
                    usage_recorded = True
                if chunk.delta.strip():
                    produced_text = True
                elif chunk.finish_reason == _LENGTH_LIMIT and not produced_text:
                    # Cut off before any visible text: fail instead of ending an empty reply.
                    # Nothing visible has reached the caller, so failing here loses nothing.
                    raise LLMOutputTruncatedError(
                        _NO_OUTPUT_MESSAGE,
                        provider=self._provider.name,
                        request_id=chunk.request_id,
                    )
                yield chunk
        except LLMError as exc:
            self._record_call_end(
                model_role, "stream_chat_completion", start, outcome="error", error=exc
            )
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
            self._record_call_end(model_role, "stream_chat_completion", start, outcome="success")
            logger.info(
                "llm_stream_completed",
                provider=self._provider.name,
                model=model,
                model_role=model_role.value,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )

    async def _with_deadline(
        self, stream: AsyncIterator[StreamChunk]
    ) -> AsyncIterator[StreamChunk]:
        """Yields from `stream`, failing with `LLMTimeoutError` once the whole stream has run for
        `llm_stream_total_timeout_seconds`, however slowly the provider keeps it alive. The wait for
        each chunk is bounded by what is left of the budget, and the provider stream is closed."""
        budget = self._settings.llm_stream_total_timeout_seconds
        deadline = time.monotonic() + budget
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMTimeoutError(
                        f"The model stream exceeded {budget:g} seconds",
                        provider=self._provider.name,
                    )
                try:
                    chunk = await asyncio.wait_for(anext(stream), timeout=remaining)
                except StopAsyncIteration:
                    return
                except TimeoutError:
                    raise LLMTimeoutError(
                        f"The model stream exceeded {budget:g} seconds",
                        provider=self._provider.name,
                    ) from None
                yield chunk
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

    def _record_call_end(
        self,
        model_role: ModelRole,
        operation: str,
        start: float,
        *,
        outcome: str,
        error: BaseException | None = None,
    ) -> None:
        """Metrics for one finished provider call (labels are bounded; see app.observability)."""
        name = self._provider.name
        metrics.record_llm_duration(name, operation, time.perf_counter() - start)
        metrics.record_llm_request(name, model_role.value, operation, outcome, error)

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
                delay = _backoff_delay(attempt, exc)
                if attempt >= max_attempts or delay > _MAX_RETRY_WAIT_SECONDS:
                    self._record_call_end(model_role, operation, start, outcome="error", error=exc)
                    logger.warning(
                        "llm_request_failed",
                        provider=self._provider.name,
                        model=model,
                        model_role=model_role.value,
                        operation=operation,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        duration_ms=duration_ms,
                        requested_wait_seconds=delay if delay > _MAX_RETRY_WAIT_SECONDS else None,
                    )
                    raise
                metrics.record_llm_duration(
                    self._provider.name, operation, time.perf_counter() - start
                )
                metrics.record_llm_retry(self._provider.name, exc)
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
            except Exception as exc:
                # LLMError or anything a provider SDK leaks: count the failure, then re-raise.
                self._record_call_end(model_role, operation, start, outcome="error", error=exc)
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
                self._record_call_end(model_role, operation, start, outcome="success")
                metrics.record_llm_tokens(
                    self._provider.name, model_role.value, getattr(result, "usage", None)
                )
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
        "reasoning_tokens": getattr(usage, "reasoning_tokens", None),  # a count, never the text
    }


def _cut_off_without_output(response: CompletionResponse) -> bool:
    """True only for blank content with no tool call at the output limit: partial text and tool
    calls (whose content is legitimately empty) are valid responses."""
    return (
        response.finish_reason == _LENGTH_LIMIT
        and not response.content.strip()
        and not response.tool_calls
    )


def _backoff_delay(attempt: int, exc: Exception) -> float:
    base_delay = min(0.5 * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        return max(base_delay, float(retry_after))
    return base_delay


@lru_cache
def get_llm_gateway() -> LLMGateway:
    return LLMGateway(get_settings())
