"""Child-process entry points for test_isolated_extraction.py.

A spawned child imports the module its target lives in, so these live in a module of their own
that imports nothing but the application's extraction types (no pytest, no fixtures). Each has the
same signature as `app.documents.isolated_extraction.extract_in_child`. Where a test needs to
observe the child, `content` carries a file path instead of document bytes.
"""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection
from pathlib import Path

from app.documents.extractors.base import ExtractionLimits, ExtractionResult
from app.documents.isolated_extraction import scrub_environment


def hang_and_heartbeat(
    connection: Connection, document_type: str, limits: ExtractionLimits, content: bytes
) -> None:
    """A parser that never finishes: appends a line to the file every 50 ms, forever."""
    path = Path(content.decode("utf-8"))
    while True:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        time.sleep(0.05)


def die_without_answering(
    connection: Connection, document_type: str, limits: ExtractionLimits, content: bytes
) -> None:
    """A parser that crashes the whole process (as a native-code fault would)."""
    os._exit(3)


def raise_unexpected(
    connection: Connection, document_type: str, limits: ExtractionLimits, content: bytes
) -> None:
    """Runs the real entry point's error handling with a failure no extractor anticipates."""
    from app.documents import isolated_extraction

    def broken(*_args: object, **_kwargs: object) -> object:
        raise ValueError("internal parser detail that must not reach the user")

    isolated_extraction.get_extractor = broken  # type: ignore[assignment]
    isolated_extraction.extract_in_child(connection, document_type, limits, content)


def report_environment(
    connection: Connection, document_type: str, limits: ExtractionLimits, content: bytes
) -> None:
    """Scrubs the environment exactly as the real entry point does, then reports what is left."""
    scrub_environment()
    connection.send(("ok", ExtractionResult(pages=["\n".join(sorted(os.environ))])))
    connection.close()
