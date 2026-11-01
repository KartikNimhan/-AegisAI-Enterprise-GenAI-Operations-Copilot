"""Text extraction from untrusted files in a separate process with a hard deadline (AIGSEC-003).

The extraction limits (`ExtractionLimits`) bound how much a file may expand to, but not how long a
parser may take: a crafted PDF can make every page slow to parse. In a thread that cannot be
stopped (a Python thread cannot be killed, and `asyncio.wait_for` around `asyncio.to_thread` only
stops *waiting*: the parser keeps running and keeps its thread), so a few hostile uploads could tie
up the worker threads indefinitely. Here each extraction runs in a child process instead:

- **Hard deadline.** The child gets `timeout_seconds` (from process start). When it is exceeded the
  child is terminated, then killed if it does not exit, and the document fails with
  `ExtractionTimeoutError` — a safe message with no parser detail.
- **Windows-safe.** The `spawn` start method is used everywhere (it is the only one on Windows), so
  the child starts from a fresh interpreter and inherits no memory from the server, such as loaded
  settings or open connections.
- **No secrets.** A spawned child still inherits environment variables, so it removes everything
  but a short allowlist of OS variables before it reads a single byte of the file.
- **Bounded.** At most `max_concurrency` extractions run at once per event loop; the slot is held
  until the child is gone, even when the request that started it was cancelled, so abandoned work
  cannot pile up beyond that bound, and each piece is itself bounded by the deadline.

Only plain data crosses the process boundary: the file bytes and limits in, an `ExtractionResult`
(or an error kind) out.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import weakref
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from app.documents.exceptions import ExtractionError
from app.documents.extractors import get_extractor
from app.documents.extractors.base import ExtractionLimits, ExtractionResult
from app.domain.enums.document_type import DocumentType

if TYPE_CHECKING:
    from app.config import Settings

logger = structlog.get_logger(__name__)

# Environment variables a child keeps: what the OS and Python need to run, nothing else.
_CHILD_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PATHEXT",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
)
# How long to wait for a terminated child to exit before killing it, and after killing it.
_STOP_GRACE_SECONDS = 5.0


class ExtractionTimeoutError(ExtractionError):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(
            f"Text extraction took longer than the allowed {timeout_seconds:g} seconds "
            "and was stopped"
        )


class ExtractionRunner(Protocol):
    async def extract(
        self, document_type: DocumentType, limits: ExtractionLimits, content: bytes
    ) -> ExtractionResult: ...


class InProcessExtractionRunner:
    """Runs the extractor in a worker thread, as before AIGSEC-003, with no deadline. Only for
    tests that exercise what happens around extraction, never for serving untrusted files."""

    async def extract(
        self, document_type: DocumentType, limits: ExtractionLimits, content: bytes
    ) -> ExtractionResult:
        return await asyncio.to_thread(get_extractor(document_type, limits).extract, content)


def scrub_environment(environ: Any = None) -> None:
    """Removes every environment variable outside the allowlist (API keys, database URLs,
    passwords), so a parser exploit in the child finds no credential."""
    environ = os.environ if environ is None else environ
    for key in list(environ):
        if key.upper() not in _CHILD_ENVIRONMENT_ALLOWLIST:
            del environ[key]


def extract_in_child(
    connection: Connection, document_type: str, limits: ExtractionLimits, content: bytes
) -> None:
    """The child process's entry point. Sends back exactly one `(kind, payload)` message."""
    scrub_environment()
    try:
        result = get_extractor(DocumentType(document_type), limits).extract(content)
        connection.send(("ok", result))
    except ExtractionError as exc:
        # These messages are written for users (e.g. "The PDF has 3000 pages, over the limit").
        connection.send(("extraction_error", str(exc)))
    except BaseException as exc:  # noqa: BLE001 - the child must always answer, then exit
        connection.send(("internal_error", type(exc).__name__))
    finally:
        connection.close()


ChildTarget = Callable[[Connection, str, ExtractionLimits, bytes], None]


class _PerLoopLimiter:
    """One semaphore per event loop (asyncio primitives belong to one loop), shared by every
    runner in that loop, so the bound is process-wide rather than per request."""

    def __init__(self) -> None:
        self._semaphores: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, dict[int, asyncio.Semaphore]
        ] = weakref.WeakKeyDictionary()

    def semaphore(self, limit: int) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        per_limit = self._semaphores.setdefault(loop, {})
        if limit not in per_limit:
            per_limit[limit] = asyncio.Semaphore(limit)
        return per_limit[limit]


_LIMITER = _PerLoopLimiter()


class IsolatedExtractionRunner:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_concurrency: int,
        target: ChildTarget = extract_in_child,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_concurrency = max_concurrency
        self._target = target

    async def extract(
        self, document_type: DocumentType, limits: ExtractionLimits, content: bytes
    ) -> ExtractionResult:
        semaphore = _LIMITER.semaphore(self._max_concurrency)
        await semaphore.acquire()
        try:
            future = asyncio.get_running_loop().run_in_executor(
                None, self._run_blocking, document_type.value, limits, content
            )
        except BaseException:
            semaphore.release()
            raise
        # Released when the child is gone, not when the awaiting request goes away.
        future.add_done_callback(lambda _f: semaphore.release())
        return await asyncio.shield(future)

    def _run_blocking(
        self, document_type: str, limits: ExtractionLimits, content: bytes
    ) -> ExtractionResult:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=self._target,
            args=(sender, document_type, limits, content),
            daemon=True,
            name="aegisai-extraction",
        )
        process.start()
        sender.close()  # only the child writes; the parent sees EOF if the child dies
        try:
            if not receiver.poll(self._timeout_seconds):
                logger.warning(
                    "document_extraction_timed_out",
                    document_type=document_type,
                    timeout_seconds=self._timeout_seconds,
                )
                raise ExtractionTimeoutError(self._timeout_seconds)
            try:
                kind, payload = receiver.recv()
            except EOFError as exc:
                raise RuntimeError("the extraction process exited without a result") from exc
        finally:
            receiver.close()
            _stop(process)

        if kind == "ok":
            return payload
        if kind == "extraction_error":
            raise ExtractionError(payload)
        # An unexpected failure inside the parser: the document gets the generic internal-error
        # message (DocumentService._safe_error_message); only the exception's type is logged.
        logger.warning("document_extraction_crashed", error_type=str(payload))
        raise RuntimeError("the extraction process failed")


def _stop(process: BaseProcess) -> None:
    """Make sure the child is gone and its resources released, whatever state it is in."""
    process.join(timeout=0.5 if process.is_alive() else None)
    if process.is_alive():
        process.terminate()
        process.join(_STOP_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(_STOP_GRACE_SECONDS)
    if not process.is_alive():
        process.close()


def build_extraction_runner(settings: Settings) -> ExtractionRunner:
    """The runner the application serves uploads with."""
    return IsolatedExtractionRunner(
        timeout_seconds=settings.document_extraction_timeout_seconds,
        max_concurrency=settings.document_extraction_max_concurrency,
    )
