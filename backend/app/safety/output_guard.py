"""Redacting credential-like values and high-confidence personal data from model output and tool
results (AIGSEC-015).

A model can repeat whatever reached its context: a password in an uploaded document, a key in a
tool result, an injected instruction to print a token. Before an answer reaches a user, is stored,
or a tool result reaches the model, `OutputGuard` replaces values that look like credentials (and,
by default, payment card and social-security-style numbers) with a marker such as
`[REDACTED:credential]`. It is deterministic and costs nothing per call: the `safety` model role is
deliberately not used for a second, billed and fallible model call.

What it is NOT
--------------
- Not complete secret or PII detection. It recognises specific, well-known shapes (listed in
  `_RULES`); an unusual secret, a name or an address passes through. Contact details (e-mail
  addresses, phone numbers) are often legitimate content, so redacting them is opt-in
  (`OUTPUT_GUARD_REDACT_CONTACT_DETAILS`).
- Not a hallucination or prompt-injection defence. Citation ids are checked separately against
  what was really retrieved (`app.rag.citations`), which proves a cited source exists, not that it
  supports the sentence (ADR 017, D-5).

Streaming and final text are the same
-------------------------------------
`StreamingOutputGuard` emits text only up to a whitespace boundary and holds back anything that
could still become a match (an unfinished token, a `password =` waiting for its value, a run of
card-number digits, an open private-key block). `OutputGuard.redact` runs that same algorithm over
the whole text at once, so a streamed answer and the stored answer are redacted identically; a
test checks this for arbitrary chunkings. The hold is bounded, so the stream never stalls.

Nothing it finds is logged: only the kinds and the count.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

CREDENTIAL = "credential"
PRIVATE_KEY = "private_key"
CARD_NUMBER = "card_number"
NATIONAL_ID = "national_id"
EMAIL = "email"
PHONE = "phone"

# Longest text held back while waiting to see whether it completes a match. A private-key block
# may be held up to `_MAX_PEM_HOLD`; anything held longer is released (still redacted).
_MAX_HOLD = 512
_MAX_PEM_HOLD = 16_384

_PEM_BEGIN = "-----BEGIN"
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")
_PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_KEY_WORDS = (
    r"password|passwd|pwd|passphrase|secret|client[_-]?secret|api[_-]?key|access[_-]?key"
    r"|auth[_-]?token|access[_-]?token|refresh[_-]?token|private[_-]?key"
)
_KEY_VALUE = re.compile(
    rf"(?i)\b({_KEY_WORDS})\b(\s*[:=]\s*)([\"']?)(?!\[REDACTED)([^\s\"'<>]{{6,}})\3"
)
# A key word (and maybe its separator) at the very end of the text: its value may still come.
_KEY_PENDING = re.compile(rf"(?i)\b(?:{_KEY_WORDS}|bearer)\b\s*[:=]?\s*$")
# Digits at the end that start a token (a card number may still be arriving in groups).
_DIGITS_PENDING = re.compile(r"(?:(?<=\s)|^)(?:\d[ -]?){1,22}$")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _card(match: re.Match[str]) -> str | None:
    digits = re.sub(r"[ -]", "", match.group(0))
    return f"[REDACTED:{CARD_NUMBER}]" if 13 <= len(digits) <= 19 and _luhn_valid(digits) else None


def _key_value(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}[REDACTED:{CREDENTIAL}]"


def _url_credentials(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}:[REDACTED:{CREDENTIAL}]@"


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    # None replaces the whole match with `[REDACTED:<kind>]`; a function may keep context (the
    # key name, the URL's user) or return None to leave a non-match (a non-Luhn number) alone.
    replace: Callable[[re.Match[str]], str | None] | None = None
    contact: bool = False


_RULES: tuple[_Rule, ...] = (
    _Rule(PRIVATE_KEY, _PEM),
    _Rule(CREDENTIAL, re.compile(r"\b(?:gsk|sk|rk)[_-][A-Za-z0-9_-]{20,}")),  # Groq/OpenAI style
    _Rule(CREDENTIAL, re.compile(r"\bAKIA[0-9A-Z]{16}\b")),  # AWS access key id
    _Rule(CREDENTIAL, re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    _Rule(CREDENTIAL, re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),  # Slack
    _Rule(CREDENTIAL, re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),  # Google API key
    _Rule(  # a JSON Web Token: three base64url parts, the first two JSON objects
        CREDENTIAL, re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
    ),
    _Rule(CREDENTIAL, re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    _Rule(  # scheme://user:password@host keeps scheme and user
        CREDENTIAL,
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s:/@]+):([^\s/@]+)@"),
        _url_credentials,
    ),
    _Rule(CREDENTIAL, _KEY_VALUE, _key_value),
    # Not next to a letter, digit, underscore or hyphen: inside an identifier such as a UUID
    # ("77599839-2495-4006-91dd-…") the digits read across the hyphens can form a Luhn-valid run,
    # and redacting it corrupted ids in tool results (agent sources failed to parse).
    _Rule(CARD_NUMBER, re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])"), _card),
    _Rule(NATIONAL_ID, re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),  # US SSN shape
    _Rule(
        EMAIL,
        re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}\b"),
        contact=True,
    ),
    _Rule(PHONE, re.compile(r"(?<![\w+])\+\d{8,15}\b"), contact=True),  # E.164 numbers only
)


@dataclass(frozen=True)
class GuardResult:
    text: str
    # One entry per redaction, the kind only (never the value).
    findings: tuple[str, ...]


class OutputGuard:
    def __init__(self, *, enabled: bool = True, redact_contact_details: bool = False) -> None:
        self._enabled = enabled
        self._rules = tuple(r for r in _RULES if redact_contact_details or not r.contact)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def redact_segment(self, text: str) -> GuardResult:
        """Applies every rule to one complete piece of text."""
        if not self._enabled or not text:
            return GuardResult(text=text, findings=())
        findings: list[str] = []
        for rule in self._rules:
            text = rule.pattern.sub(lambda m, rule=rule: _apply(rule, m, findings), text)
        return GuardResult(text=text, findings=tuple(findings))

    def redact(self, text: str) -> GuardResult:
        """The final text: the streaming algorithm over the whole text, so both paths agree."""
        stream = self.stream()
        out = stream.feed(text) + stream.finish()
        return GuardResult(text=out, findings=stream.findings)

    def stream(self) -> StreamingOutputGuard:
        return StreamingOutputGuard(self)

    def redact_data(self, value: Any) -> tuple[Any, tuple[str, ...]]:
        """Every string inside a JSON-like structure (a tool result), redacted in place of the
        original; keys are kept. Structure and types are unchanged, so the result serialises as
        before."""
        findings: list[str] = []

        def walk(item: Any) -> Any:
            if isinstance(item, str):
                result = self.redact(item)
                findings.extend(result.findings)
                return result.text
            if isinstance(item, Mapping):
                return {key: walk(inner) for key, inner in item.items()}
            if isinstance(item, list | tuple):
                return type(item)(walk(inner) for inner in item)
            return item

        return walk(value), tuple(findings)


def _apply(rule: _Rule, match: re.Match[str], findings: list[str]) -> str:
    replacement = f"[REDACTED:{rule.kind}]" if rule.replace is None else rule.replace(match)
    if replacement is None:
        return match.group(0)
    findings.append(rule.kind)
    return replacement


class StreamingOutputGuard:
    def __init__(self, guard: OutputGuard) -> None:
        self._guard = guard
        self._held = ""
        self._findings: list[str] = []

    @property
    def findings(self) -> tuple[str, ...]:
        return tuple(self._findings)

    def feed(self, delta: str) -> str:
        """The text that is safe to send now (possibly empty while a match may be pending)."""
        if not self._guard.enabled:
            return delta
        self._held += delta
        cut = self._safe_cut(self._held)
        if cut == 0:
            return ""
        ready, self._held = self._held[:cut], self._held[cut:]
        return self._emit(ready)

    def finish(self) -> str:
        """Everything still held, redacted."""
        held, self._held = self._held, ""
        return self._emit(held) if self._guard.enabled else held

    def _emit(self, text: str) -> str:
        result = self._guard.redact_segment(text)
        self._findings.extend(result.findings)
        return result.text

    def _safe_cut(self, text: str) -> int:
        """How much of `text` can be released: up to its last whitespace, minus anything that
        could still be the start of a match, within the hold bounds. Every cut is right after a
        whitespace character, so each released segment starts where a match could start in the
        whole text too (the rules' look-behinds then see the same thing on both paths)."""
        block_end = -1
        begin = text.rfind(_PEM_BEGIN)
        if begin != -1:
            tail = text[begin:]
            header = tail.split("\n", 1)[0]
            end = _PEM_END.search(tail)
            open_key = "PRIVATE KEY" in header and end is None
            header_arriving = "\n" not in tail and len(tail) < 64
            if (open_key and len(tail) <= _MAX_PEM_HOLD) or header_arriving:
                return _whitespace_before(text, begin)
            if end is not None:
                block_end = begin + end.end()

        cut = _whitespace_before(text, len(text))
        if begin != -1 and begin < cut < block_end:
            # The END line has spaces in it: release the complete block, never half of it.
            cut = block_end
        if cut == 0:
            # One unbroken token: wait for it to finish, within the bound.
            return 0 if len(text) <= _MAX_HOLD else len(text)
        for pending in (_KEY_PENDING, _DIGITS_PENDING):
            match = pending.search(text, 0, cut)
            if match is not None and len(text) - match.start() <= _MAX_HOLD:
                cut = _whitespace_before(text, match.start())
        return cut


def _whitespace_before(text: str, index: int) -> int:
    """The position just after the last whitespace before `index` (0 when there is none)."""
    for position in range(index - 1, -1, -1):
        if text[position].isspace():
            return position + 1
    return 0


def log_findings(event: str, findings: tuple[str, ...], **context: Any) -> None:
    """Records that something was redacted: the kinds and how many, never the values."""
    if findings:
        logger.warning(event, kinds=sorted(set(findings)), count=len(findings), **context)


def build_output_guard(settings: Any) -> OutputGuard:
    return OutputGuard(
        enabled=settings.output_guard_enabled,
        redact_contact_details=settings.output_guard_redact_contact_details,
    )
