"""The metrics module: off by default, a dedicated registry, bounded labels, safe recording."""

from __future__ import annotations

import inspect

import pytest

from app.llm import exceptions as llm_exceptions
from app.llm.schemas import TokenUsage
from app.observability import metrics

from .helpers import exposition, samples, value


def test_nothing_is_recorded_or_exposed_while_disabled() -> None:
    metrics.reset(enabled=False)

    metrics.record_http_request("GET", "/health", 200, 0.01)
    metrics.record_rate_limit_refusal("llm")
    metrics.record_llm_request("groq", "primary", "chat_completion", "success")
    metrics.record_llm_tokens("groq", "primary", TokenUsage(input_tokens=5, output_tokens=5))

    assert samples() == []
    assert metrics.is_enabled() is False


def test_only_the_applications_own_series_are_exposed() -> None:
    metrics.record_http_request("GET", "/health", 200, 0.01)

    names = {name for name, _, _ in samples()}

    assert names and all(name.startswith("aegis_") for name in names)
    text = exposition()
    for default_collector in ("process_", "python_", "gc_", "platform"):
        assert default_collector not in text


def test_the_registry_is_not_the_default_one() -> None:
    from prometheus_client import REGISTRY

    assert metrics._current.registry is not REGISTRY


def test_no_series_uses_a_label_outside_the_allowlist() -> None:
    collectors = metrics._current.registry._collector_to_names  # the registered instruments

    used = {label for collector in collectors for label in getattr(collector, "_labelnames", ())}

    assert used and used <= metrics.ALLOWED_LABEL_NAMES
    for label in used:
        for identity_word in ("user", "org", "email", "request", "conversation", "document"):
            assert identity_word not in label
        assert label not in {"id", "path", "file", "filename", "message", "error"}


def test_http_duration_help_says_it_is_not_the_total_stream_duration() -> None:
    metrics.record_http_request("GET", "/health", 200, 0.01)
    text = exposition()

    help_line = next(
        line for line in text.splitlines() if line.startswith("# HELP aegis_http_request_duration")
    )
    assert "STARTED" in help_line and "NOT the total stream duration" in help_line


# -- label normalisation -------------------------------------------------------------------


def test_unknown_methods_and_odd_statuses_collapse_to_fixed_values() -> None:
    metrics.record_http_request("BREW", "/x", 200, 0.0)
    metrics.record_http_request("get", "/x", 99999, 0.0)

    assert value("aegis_http_requests_total", method="OTHER", route="/x", status="200") == 1
    assert value("aegis_http_requests_total", method="GET", route="/x", status="other") == 1


def test_a_missing_route_is_the_fixed_unmatched_label() -> None:
    metrics.record_http_request("GET", None, 404, 0.0)
    metrics.record_http_request("GET", "", 404, 0.0)

    assert value("aegis_http_requests_total", route="unmatched", status="404") == 2


@pytest.mark.parametrize(
    "hostile",
    [
        "alice@example.test",
        "123e4567-e89b-12d3-a456-426614174000" * 2,
        "UPPER CASE WITH SPACES",
        "a" * 200,
        "",
        'quote"newline\n',
        "../../etc/passwd",
    ],
)
def test_free_form_values_can_never_become_label_values(hostile: str) -> None:
    metrics.record_llm_request(hostile, hostile, hostile, hostile)
    metrics.record_rate_limit_refusal(hostile)

    for _, labels, _ in samples():
        for label_value in labels.values():
            assert label_value != hostile or label_value == "other"
            assert "@" not in label_value and len(label_value) <= 32
    assert value("aegis_rate_limit_refusals_total", bucket="other") == 1


def test_error_types_are_limited_to_the_known_llm_exception_classes() -> None:
    metrics.record_llm_request("groq", "primary", "chat_completion", "error", ValueError("x"))
    metrics.record_llm_request(
        "groq", "primary", "chat_completion", "error", llm_exceptions.LLMTimeoutError("t")
    )

    assert value("aegis_llm_errors_total", error_type="other") == 1
    assert value("aegis_llm_errors_total", error_type="LLMTimeoutError") == 1


def test_the_known_error_types_match_the_llm_exception_module() -> None:
    defined = {
        name
        for name, cls in inspect.getmembers(llm_exceptions, inspect.isclass)
        if issubclass(cls, llm_exceptions.LLMError)
    }

    assert defined == metrics.KNOWN_LLM_ERROR_TYPES


# -- tokens ----------------------------------------------------------------------------------


def test_token_usage_adds_only_reported_positive_integers() -> None:
    metrics.record_llm_tokens("groq", "primary", TokenUsage(input_tokens=7, output_tokens=3))
    metrics.record_llm_tokens("groq", "primary", TokenUsage(input_tokens=None, output_tokens=4))
    metrics.record_llm_tokens("groq", "primary", TokenUsage())  # nothing reported
    metrics.record_llm_tokens("groq", "primary", None)
    metrics.record_llm_tokens("groq", "primary", TokenUsage.model_construct(input_tokens=-5))
    metrics.record_llm_tokens("groq", "primary", TokenUsage.model_construct(input_tokens=True))
    metrics.record_llm_tokens("groq", "primary", object())

    assert value("aegis_llm_tokens_total", direction="input") == 7
    assert value("aegis_llm_tokens_total", direction="output") == 7


# -- never breaks traffic ----------------------------------------------------------------------


def test_a_failure_while_recording_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def labels(self, *args: object) -> None:
            raise RuntimeError("registry exploded")

    monkeypatch.setattr(metrics._current, "http_requests", Broken())

    assert metrics.record_http_request("GET", "/health", 200, 0.01) is None  # no exception


def test_llm_labels_outside_the_known_sets_fold_into_other() -> None:
    usage = type("U", (), {"input_tokens": 3, "output_tokens": 0})()
    metrics.record_llm_request("groq", "user-chosen-role", "made_up_op", "weird")
    metrics.record_llm_tokens("groq", "user-chosen-role", usage)

    assert (
        value("aegis_llm_requests_total", model_role="other", operation="other", outcome="other")
        == 1
    )
    assert value("aegis_llm_tokens_total", model_role="other", direction="input") == 3
    assert "user-chosen-role" not in exposition()


def test_every_real_model_role_keeps_its_own_label() -> None:
    from app.llm.schemas import ModelRole

    for role in ModelRole:
        metrics.record_llm_request("groq", role.value, "chat_completion", "success")
        metrics.record_llm_request("groq", role.value, "stream_chat_completion", "error")

    for role in ModelRole:
        assert value("aegis_llm_requests_total", model_role=role.value, outcome="success") == 1
        assert value("aegis_llm_requests_total", model_role=role.value, outcome="error") == 1
