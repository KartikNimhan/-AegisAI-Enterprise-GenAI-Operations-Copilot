"""The startup warm-up task is kept referenced while it runs and cleaned up at shutdown."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.main import create_app


def make_app():
    return create_app(Settings(_env_file=None, debug=True, environment="local"))  # type: ignore[call-arg]


def test_the_warm_up_task_is_referenced_by_the_app_while_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def slow_warm_up() -> None:
        started.set()
        await asyncio.sleep(3600)  # still "loading" when the app shuts down

    monkeypatch.setattr(main_module, "_warm_up_embedding_model", slow_warm_up)
    application = make_app()

    with TestClient(application):
        task = application.state.embedding_warm_up
        assert isinstance(task, asyncio.Task)

    # Shutdown cancelled the unfinished warm-up instead of abandoning it.
    assert task.cancelled() or task.done()


def test_a_finished_warm_up_is_left_alone_at_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def quick_warm_up() -> None:
        return None

    monkeypatch.setattr(main_module, "_warm_up_embedding_model", quick_warm_up)
    application = make_app()

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200

    task = application.state.embedding_warm_up
    assert task.done() and not task.cancelled()
