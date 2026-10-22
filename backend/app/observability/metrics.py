"""Application metrics: a small, bounded set of Prometheus series.

See docs/operations/observability.md.

Design rules, enforced by tests:

- **Off by default.** Until `configure(enabled=True)` is called (by `create_app`, from
  `METRICS_ENABLED`) every `record_*` function returns immediately and nothing is stored.
- **Dedicated registry.** Only the series defined here are exposed. The default registry, with its
  `process_*` and `python_*` collectors (memory, file descriptors, interpreter details), is never
  used.
- **Bounded labels only.** Every label value is either produced by this module from a fixed
  vocabulary or sanitised by `_label` (a short, lower-case token, else a fixed fallback). Labels
  never carry user ids, organization ids, e-mail addresses, conversation, document or request ids,
  file names, model output or error messages; routes are route *templates*
  (`/api/v1/documents/{document_id}`), and a request that matched no route is `unmatched`.
- **Never break traffic.** A failure while recording is swallowed (and logged at debug level): a
  metrics bug must not change a response.

Per-process: the counters live in this process's memory (the backend runs one uvicorn process).
With several workers each would report its own counts.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client import generate_latest as _generate_latest

from app.llm.schemas import ModelRole

logger = structlog.get_logger(__name__)

PREFIX = "aegis_"
CONTENT_TYPE = CONTENT_TYPE_LATEST

UNMATCHED_ROUTE = "unmatched"
OTHER = "other"

_KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
# The names of `app.llm.exceptions.LLMError` and its subclasses. A test keeps this in step with
# that module; anything else is reported as `other` so an unexpected class name cannot create
# series.
KNOWN_LLM_ERROR_TYPES = frozenset(
    {
        "LLMError",
        "LLMAuthenticationError",
        "LLMRateLimitError",
        "LLMTimeoutError",
        "LLMProviderUnavailableError",
        "LLMInvalidRequestError",
        "LLMProviderError",
    }
)
_LABEL_VALUE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,31}")

HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
LLM_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)

# Every label name used by any series. A test asserts no series uses a name outside this set, so a
# future change cannot quietly add an identity-bearing label.
ALLOWED_LABEL_NAMES = frozenset(
    {
        "method",
        "route",
        "status",
        "bucket",
        "provider",
        "model_role",
        "operation",
        "outcome",
        "error_type",
        "direction",
    }
)


def _label(value: object, fallback: str = OTHER) -> str:
    """A bounded label value: a short lower-case token, otherwise `fallback`."""
    text = str(value).lower() if value is not None else ""
    return text if _LABEL_VALUE.fullmatch(text) else fallback


# Closed value sets for the LLM labels the application itself defines. Anything else (a future
# role or operation not yet listed here, or a bug) is folded into `other` rather than minting a
# series. `provider` is only shape-checked, since providers are pluggable.
LLM_MODEL_ROLES = frozenset(role.value for role in ModelRole)
LLM_OPERATIONS = frozenset({"chat_completion", "stream_chat_completion"})
LLM_OUTCOMES = frozenset({"success", "error"})


def _choice(value: object, allowed: frozenset[str]) -> str:
    text = _label(value)
    return text if text in allowed else OTHER


def normalize_method(method: str) -> str:
    upper = method.upper()
    return upper if upper in _KNOWN_METHODS else "OTHER"


def normalize_status(status_code: int) -> str:
    return str(status_code) if 100 <= status_code <= 599 else "other"


def llm_error_type(exc_or_name: BaseException | str) -> str:
    name = exc_or_name if isinstance(exc_or_name, str) else type(exc_or_name).__name__
    return name if name in KNOWN_LLM_ERROR_TYPES else OTHER


class AppMetrics:
    """One registry plus its instruments. A fresh instance is a clean slate (used by tests)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            f"{PREFIX}http_requests_total",
            "HTTP requests completed, by method, route template and status code.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.http_duration = Histogram(
            f"{PREFIX}http_request_duration_seconds",
            "Time until the response STARTED (headers ready), by method and route template. "
            "For streaming (SSE) endpoints this is NOT the total stream duration.",
            ["method", "route"],
            buckets=HTTP_BUCKETS,
            registry=self.registry,
        )
        self.rate_limit_refusals = Counter(
            f"{PREFIX}rate_limit_refusals_total",
            "Requests refused by a per-user rate limit (HTTP 429), by bucket.",
            ["bucket"],
            registry=self.registry,
        )
        self.rate_limiter_unavailable = Counter(
            f"{PREFIX}rate_limiter_unavailable_total",
            "Requests refused (HTTP 503) because the rate limiter itself failed, by bucket.",
            ["bucket"],
            registry=self.registry,
        )
        self.llm_requests = Counter(
            f"{PREFIX}llm_requests_total",
            "LLM gateway calls by final outcome (retries are counted separately).",
            ["provider", "model_role", "operation", "outcome"],
            registry=self.registry,
        )
        self.llm_errors = Counter(
            f"{PREFIX}llm_errors_total",
            "LLM gateway calls that failed, by error class.",
            ["provider", "error_type"],
            registry=self.registry,
        )
        self.llm_retries = Counter(
            f"{PREFIX}llm_retries_total",
            "LLM gateway retries after a retryable error, by error class.",
            ["provider", "error_type"],
            registry=self.registry,
        )
        self.llm_duration = Histogram(
            f"{PREFIX}llm_request_duration_seconds",
            "Duration of one provider call (one attempt). For stream_chat_completion it is the "
            "whole stream.",
            ["provider", "operation"],
            buckets=LLM_BUCKETS,
            registry=self.registry,
        )
        self.llm_tokens = Counter(
            f"{PREFIX}llm_tokens_total",
            "Tokens reported by the provider, by direction (input or output). Calls whose usage "
            "was not reported add nothing.",
            ["provider", "model_role", "direction"],
            registry=self.registry,
        )


_current = AppMetrics()
_enabled = False


def configure(*, enabled: bool) -> None:
    """Turns recording on or off (called once by `create_app`). Turning it off does not clear
    what was already recorded; `reset` does."""
    global _enabled
    _enabled = enabled


def reset(*, enabled: bool = False) -> None:
    """A fresh registry and the given on/off state. For tests."""
    global _current, _enabled
    _current = AppMetrics()
    _enabled = enabled


def is_enabled() -> bool:
    return _enabled


def render() -> bytes:
    """The exposition text for the dedicated registry."""
    return _generate_latest(_current.registry)


def _safely[**P, R](function: Callable[P, R]) -> Callable[P, R | None]:
    """Recording is best effort: it does nothing when disabled and never raises."""

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        if not _enabled:
            return None
        try:
            return function(*args, **kwargs)
        except Exception:
            logger.debug("metrics_recording_failed", exc_info=True)
            return None

    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    return wrapper


@_safely
def record_http_request(method: str, route: str | None, status_code: int, seconds: float) -> None:
    template = route if route else UNMATCHED_ROUTE
    verb = normalize_method(method)
    _current.http_requests.labels(verb, template, normalize_status(status_code)).inc()
    _current.http_duration.labels(verb, template).observe(max(0.0, seconds))


@_safely
def record_rate_limit_refusal(bucket: str) -> None:
    _current.rate_limit_refusals.labels(_label(bucket)).inc()


@_safely
def record_rate_limiter_unavailable(bucket: str) -> None:
    _current.rate_limiter_unavailable.labels(_label(bucket)).inc()


@_safely
def record_llm_request(
    provider: str, model_role: str, operation: str, outcome: str, error: BaseException | None = None
) -> None:
    prov = _label(provider)
    _current.llm_requests.labels(
        prov,
        _choice(model_role, LLM_MODEL_ROLES),
        _choice(operation, LLM_OPERATIONS),
        _choice(outcome, LLM_OUTCOMES),
    ).inc()
    if error is not None:
        _current.llm_errors.labels(prov, llm_error_type(error)).inc()


@_safely
def record_llm_retry(provider: str, error: BaseException) -> None:
    _current.llm_retries.labels(_label(provider), llm_error_type(error)).inc()


@_safely
def record_llm_duration(provider: str, operation: str, seconds: float) -> None:
    _current.llm_duration.labels(_label(provider), _label(operation)).observe(max(0.0, seconds))


@_safely
def record_llm_tokens(provider: str, model_role: str, usage: Any) -> None:
    """Adds the provider-reported input/output token counts. A missing (`None`), non-integer or
    negative count adds nothing; the total is not recorded (it is the sum)."""
    if usage is None:
        return
    prov, role = _label(provider), _choice(model_role, LLM_MODEL_ROLES)
    for direction, attribute in (("input", "input_tokens"), ("output", "output_tokens")):
        count = getattr(usage, attribute, None)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            _current.llm_tokens.labels(prov, role, direction).inc(count)
