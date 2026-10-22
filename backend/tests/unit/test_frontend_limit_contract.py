"""The web composer's character cap must equal the API's, or users hit 422s the UI could prevent."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.limits import MAX_MESSAGE_CHARS

COMPOSER = Path(__file__).resolve().parents[3] / "frontend/web/src/components/Chat/Composer.tsx"


def test_composer_max_length_matches_backend_limit() -> None:
    match = re.search(r"MAX_MESSAGE_CHARS\s*=\s*([\d_]+)", COMPOSER.read_text(encoding="utf-8"))
    assert match, "Composer.tsx no longer declares MAX_MESSAGE_CHARS"
    assert int(match.group(1).replace("_", "")) == MAX_MESSAGE_CHARS
