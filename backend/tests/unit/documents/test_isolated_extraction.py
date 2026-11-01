"""Extraction in a separate process with a hard deadline (AIGSEC-003).

These start REAL child processes with the `spawn` method (the only one on Windows), using harmless
stand-ins for a hostile parser (one that never finishes, one that crashes). No malicious document
and no resource-exhaustion attack is involved: the "hang" is a sleep loop.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.documents import isolated_extraction
from app.documents.exceptions import ExtractionError
from app.documents.extractors.base import ExtractionLimits, ExtractionResult
from app.documents.isolated_extraction import (
    ExtractionTimeoutError,
    IsolatedExtractionRunner,
    build_extraction_runner,
    extract_in_child,
    scrub_environment,
)
from app.domain.enums.document_status import DocumentStatus
from app.domain.enums.document_type import DocumentType

from ...document_fixtures import make_corrupt_pdf_bytes, make_pdf_bytes, make_txt_bytes
from ..services.test_document_service import make_service
from . import extraction_children

LIMITS = ExtractionLimits()
# Generous for a real extraction (a spawned child imports the parsers first); short for a hang.
REAL_DEADLINE = 60.0
HANG_DEADLINE = 3.0


def _runner(target: Any = None, *, timeout: float = REAL_DEADLINE) -> IsolatedExtractionRunner:
    if target is None:
        return IsolatedExtractionRunner(timeout_seconds=timeout, max_concurrency=2)
    return IsolatedExtractionRunner(timeout_seconds=timeout, max_concurrency=2, target=target)


def _no_extraction_children_left() -> bool:
    return not [p for p in multiprocessing.active_children() if p.name == "aegisai-extraction"]


# -- normal extraction is unchanged ---------------------------------------------------------


async def test_a_real_text_file_is_extracted_in_a_child_process() -> None:
    result = await _runner().extract(DocumentType.TXT, LIMITS, make_txt_bytes())

    assert result.text == make_txt_bytes().decode("utf-8")
    assert _no_extraction_children_left()


async def test_a_real_pdf_is_extracted_in_a_child_process() -> None:
    result = await _runner().extract(DocumentType.PDF, LIMITS, make_pdf_bytes(text="Isolated"))

    assert "Isolated" in result.text
    assert result.metadata["page_count"] == 1


async def test_an_extraction_error_comes_back_with_its_user_facing_message() -> None:
    with pytest.raises(ExtractionError, match="Could not read PDF"):
        await _runner().extract(DocumentType.PDF, LIMITS, make_corrupt_pdf_bytes())


async def test_the_extraction_limits_still_apply_inside_the_child() -> None:
    tight = ExtractionLimits(max_pdf_pages=0)

    with pytest.raises(ExtractionError, match="over the limit of 0"):
        await _runner().extract(DocumentType.PDF, tight, make_pdf_bytes())


# -- the deadline ---------------------------------------------------------------------------


async def test_a_parser_that_never_finishes_is_stopped_at_the_deadline(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat.txt"
    runner = _runner(extraction_children.hang_and_heartbeat, timeout=HANG_DEADLINE)
    started = time.monotonic()

    with pytest.raises(ExtractionTimeoutError, match="was stopped"):
        await runner.extract(DocumentType.PDF, LIMITS, str(heartbeat).encode("utf-8"))

    elapsed = time.monotonic() - started
    assert HANG_DEADLINE <= elapsed < HANG_DEADLINE + 15  # the deadline, plus terminate/join
    # The child really is gone: it stops writing its heartbeat.
    assert heartbeat.exists()
    beats = heartbeat.read_text(encoding="utf-8").count("\n")
    await asyncio.sleep(0.5)
    assert heartbeat.read_text(encoding="utf-8").count("\n") == beats
    assert _no_extraction_children_left()


async def test_the_timeout_message_is_safe_for_users() -> None:
    message = str(ExtractionTimeoutError(60))

    assert message == "Text extraction took longer than the allowed 60 seconds and was stopped"


async def test_a_child_that_dies_without_answering_is_an_internal_failure() -> None:
    with pytest.raises(RuntimeError, match="exited without a result"):
        await _runner(extraction_children.die_without_answering).extract(
            DocumentType.PDF, LIMITS, b""
        )
    assert _no_extraction_children_left()


async def test_an_unexpected_parser_failure_does_not_leak_its_detail() -> None:
    with pytest.raises(RuntimeError) as raised:
        await _runner(extraction_children.raise_unexpected).extract(DocumentType.PDF, LIMITS, b"")

    assert "internal parser detail" not in str(raised.value)


async def test_later_extractions_still_work_after_a_timeout(tmp_path: Path) -> None:
    hanging = _runner(extraction_children.hang_and_heartbeat, timeout=HANG_DEADLINE)
    with pytest.raises(ExtractionTimeoutError):
        await hanging.extract(DocumentType.PDF, LIMITS, str(tmp_path / "beat").encode("utf-8"))

    result = await _runner().extract(DocumentType.TXT, LIMITS, b"still working")

    assert result.text == "still working"


# -- no secrets in the child -------------------------------------------------------------


async def test_the_child_keeps_no_application_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_DUMMY_SECRET_FOR_TEST", "dummy-value-not-a-real-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@localhost:1/none_test")

    result = await _runner(extraction_children.report_environment).extract(
        DocumentType.TXT, LIMITS, b""
    )

    remaining = set(result.text.split("\n")) - {""}
    assert "AEGIS_DUMMY_SECRET_FOR_TEST" not in remaining
    assert "DATABASE_URL" not in remaining
    assert remaining <= {name for name in remaining if name.upper() in _allowlist()}


def _allowlist() -> frozenset[str]:
    return isolated_extraction._CHILD_ENVIRONMENT_ALLOWLIST


def test_scrubbing_keeps_only_the_os_allowlist() -> None:
    environ = {"PATH": "x", "SystemRoot": "C:\\Windows", "GROQ_API_KEY": "k", "REDIS_PASSWORD": "p"}

    scrub_environment(environ)

    assert environ == {"PATH": "x", "SystemRoot": "C:\\Windows"}


def test_the_real_entry_point_scrubs_before_it_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Extractor:
        def extract(self, content: bytes) -> ExtractionResult:
            calls.append("extract")
            return ExtractionResult(pages=["ok"])

    class Connection:
        def send(self, message: Any) -> None:
            calls.append(f"send:{message[0]}")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(isolated_extraction, "scrub_environment", lambda: calls.append("scrub"))
    monkeypatch.setattr(isolated_extraction, "get_extractor", lambda *_a: Extractor())

    extract_in_child(Connection(), "txt", LIMITS, b"x")  # type: ignore[arg-type]

    assert calls == ["scrub", "extract", "send:ok", "close"]


# -- bounded concurrency ----------------------------------------------------------------


async def test_concurrent_extractions_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    running = 0
    peak = 0
    lock = threading.Lock()

    def fake_blocking(self: Any, *_args: Any) -> ExtractionResult:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.2)
        with lock:
            running -= 1
        return ExtractionResult(pages=["x"])

    monkeypatch.setattr(IsolatedExtractionRunner, "_run_blocking", fake_blocking)
    runner = IsolatedExtractionRunner(timeout_seconds=5, max_concurrency=2)

    await asyncio.gather(*(runner.extract(DocumentType.TXT, LIMITS, b"") for _ in range(6)))

    assert peak == 2


async def test_a_cancelled_request_keeps_its_slot_until_the_child_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started: list[int] = []

    def fake_blocking(self: Any, *_args: Any) -> ExtractionResult:
        started.append(1)
        release.wait(5)
        return ExtractionResult(pages=["x"])

    monkeypatch.setattr(IsolatedExtractionRunner, "_run_blocking", fake_blocking)
    runner = IsolatedExtractionRunner(timeout_seconds=5, max_concurrency=1)

    first = asyncio.create_task(runner.extract(DocumentType.TXT, LIMITS, b""))
    await asyncio.sleep(0.1)
    first.cancel()
    second = asyncio.create_task(runner.extract(DocumentType.TXT, LIMITS, b""))
    await asyncio.sleep(0.2)

    assert started == [1]  # the abandoned work still holds the only slot
    release.set()
    await second
    assert started == [1, 1]


# -- wiring --------------------------------------------------------------------------------


def test_the_service_uses_the_isolated_runner_with_the_configured_bounds() -> None:
    settings = Settings(
        document_extraction_timeout_seconds=12, document_extraction_max_concurrency=3
    )
    service, *_ = make_service(settings=settings)

    runner = service._extraction  # type: ignore[attr-defined]
    assert isinstance(runner, IsolatedExtractionRunner)
    assert (runner._timeout_seconds, runner._max_concurrency) == (12, 3)
    assert isinstance(build_extraction_runner(settings), IsolatedExtractionRunner)


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_extraction_timeout_seconds": 0},
        {"document_extraction_timeout_seconds": 3_601},
        {"document_extraction_max_concurrency": 0},
        {"document_extraction_max_concurrency": 65},
    ],
)
def test_out_of_range_bounds_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="DOCUMENT_EXTRACTION_"):
        Settings(**overrides)  # type: ignore[arg-type]


async def test_a_timed_out_upload_fails_cleanly_and_the_next_one_succeeds(tmp_path: Path) -> None:
    service, documents, chunks, _storage, session = make_service()

    service._extraction = _runner(  # type: ignore[attr-defined]
        extraction_children.hang_and_heartbeat, timeout=HANG_DEADLINE
    )
    # The stand-in parser reads a path from the "file", so upload a text file holding one.
    hung = await service.upload(
        filename="slow.txt",
        content_type="text/plain",
        content=str(tmp_path / "beat").encode("utf-8"),
    )

    assert hung.document.status == DocumentStatus.FAILED
    assert hung.document.error_message == (
        f"Text extraction took longer than the allowed {HANG_DEADLINE:g} seconds and was stopped"
    )
    assert chunks.chunks == []  # nothing half-processed was stored
    assert session.commit_count >= 1  # the failure was persisted

    service._extraction = _runner()  # type: ignore[attr-defined]
    ok = await service.upload(
        filename="fine.txt", content_type="text/plain", content=make_txt_bytes()
    )
    assert ok.document.status == DocumentStatus.PROCESSED
    assert documents.documents[ok.document.id].status == DocumentStatus.PROCESSED
