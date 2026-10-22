"""Every test in this package starts with a fresh, ENABLED metrics registry and leaves the
process-wide state disabled again (metrics are off by default everywhere else)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.observability import metrics


@pytest.fixture(autouse=True)
def _fresh_metrics() -> Iterator[None]:
    metrics.reset(enabled=True)
    yield
    metrics.reset(enabled=False)
