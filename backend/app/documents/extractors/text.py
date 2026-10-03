"""Plain-text extraction with explicit encoding fallback.

No dependency on `chardet`/`charset-normalizer`: a short, deterministic
chain of common encodings covers the overwhelming majority of real text
files without adding a dependency or any network-fetched data.
"""

from __future__ import annotations

from app.documents.extractors.base import DocumentExtractor, ExtractionResult

_UTF8_BOM = b"\xef\xbb\xbf"

# Tried in order after the BOM check. latin-1 (ISO-8859-1) never raises —
# every byte sequence is valid under it — so it's the deliberate last
# resort, not a first guess.
_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def decode_text_bytes(content: bytes) -> tuple[str, str]:
    """Returns (decoded_text, encoding_used)."""
    if content.startswith(_UTF8_BOM):
        return content.decode("utf-8-sig"), "utf-8-sig"

    for encoding in _ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # Unreachable in practice (latin-1 always succeeds), but keeps this
    # function total rather than relying on that fact implicitly.
    return content.decode("latin-1", errors="replace"), "latin-1 (replace)"


class PlainTextExtractor(DocumentExtractor):
    def extract(self, content: bytes) -> ExtractionResult:
        text, encoding = decode_text_bytes(content)
        return ExtractionResult(pages=[text], metadata={"encoding": encoding})
