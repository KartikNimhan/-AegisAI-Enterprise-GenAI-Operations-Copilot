"""The output guard (AIGSEC-015): what it redacts, what it leaves alone, and that streamed and final
text are guarded identically. All offline; no model is called.

Every fake credential below is ASSEMBLED AT RUNTIME from harmless pieces, so this file contains no
string a secret scanner would flag (the CI secret scan is blocking, AIGSEC-007). None of them is a
real credential.
"""

from __future__ import annotations

import json
import random

import pytest
import structlog

from app.safety.output_guard import (
    CARD_NUMBER,
    CREDENTIAL,
    EMAIL,
    NATIONAL_ID,
    PHONE,
    PRIVATE_KEY,
    OutputGuard,
    log_findings,
)

GROQ_KEY = "gsk" + "_" + "Ab3" * 12
OPENAI_KEY = "sk" + "-" + "proj" + "Zx9" * 10
AWS_KEY = "AK" + "IA" + "QWERTYUIOPASDFGH"
GITHUB_TOKEN = "gh" + "p_" + "a1B2" * 10
SLACK_TOKEN = "xo" + "xb-" + "1234567890-abcdefghij"
GOOGLE_KEY = "AI" + "za" + "S" * 35
JWT = ".".join(
    ["ey" + "J" + "hbGciOiJIUzI1NiJ9", "ey" + "J" + "zdWIiOiIxMjM0NSJ9", "c2lnbmF0dXJlLXZhbHVl"]
)
PEM = "\n".join(
    [
        "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
        "MIIEowIBAAKCAQEA" + "q" * 40,
        "q" * 56,
        "-----END " + "RSA PRIVATE" + " KEY-----",
    ]
)
CARD = "4111 " + "1111 " + "1111 " + "1111"  # a well-known test number; Luhn-valid
SSN = "123" + "-45-" + "6789"

guard = OutputGuard()


def _kinds(text: str, g: OutputGuard = guard) -> tuple[str, ...]:
    return g.redact(text).findings


# -- credentials -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret", [GROQ_KEY, OPENAI_KEY, AWS_KEY, GITHUB_TOKEN, SLACK_TOKEN, GOOGLE_KEY, JWT]
)
def test_credential_shaped_tokens_are_redacted(secret: str) -> None:
    result = guard.redact(f"Here it is: {secret} — use it carefully.")

    assert secret not in result.text
    assert "[REDACTED:credential]" in result.text
    assert result.findings == (CREDENTIAL,)
    assert result.text.endswith("— use it carefully.")


@pytest.mark.parametrize(
    "text",
    [
        "password: Summer2026!x",
        "PASSWORD = 'Summer2026!x'",
        'api_key="Summer2026xyz"',
        "client_secret=Summer2026xyz",
        "access-token: Summer2026xyz",
    ],
)
def test_key_value_secrets_keep_the_key_and_lose_the_value(text: str) -> None:
    result = guard.redact(text)

    assert "Summer2026" not in result.text
    assert "[REDACTED:credential]" in result.text
    assert result.text.split("[")[0].strip()  # the key name is still there for context


def test_a_bearer_token_is_redacted() -> None:
    assert (
        "abcdefghijklmnopqrstuvwxyz0123"
        not in guard.redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123").text
    )


def test_credentials_inside_a_url_lose_the_password_only() -> None:
    url = "postgresql+asyncpg://aegis:" + "S3cretPw" + "@db.internal:5432/aegis"

    result = guard.redact(f"Connect with {url}")

    assert "S3cretPw" not in result.text
    assert "postgresql+asyncpg://aegis:[REDACTED:credential]@db.internal:5432/aegis" in result.text


def test_a_private_key_block_is_redacted_whole() -> None:
    result = guard.redact(f"Key:\n{PEM}\nDone.")

    assert "MIIE" not in result.text and "PRIVATE KEY" not in result.text
    assert result.text == "Key:\n[REDACTED:private_key]\nDone."
    assert result.findings == (PRIVATE_KEY,)


def test_an_unterminated_private_key_is_redacted_to_the_end() -> None:
    truncated = PEM.rsplit("\n", 1)[0]

    assert "MIIE" not in guard.redact(truncated).text


# -- personal data ------------------------------------------------------------------------------


@pytest.mark.parametrize("card", [CARD, CARD.replace(" ", ""), CARD.replace(" ", "-")])
def test_luhn_valid_card_numbers_are_redacted(card: str) -> None:
    result = guard.redact(f"Card {card} expires soon")

    assert result.text == "Card [REDACTED:card_number] expires soon"
    assert result.findings == (CARD_NUMBER,)


def test_ssn_shaped_numbers_are_redacted() -> None:
    assert guard.redact(f"SSN {SSN}.").findings == (NATIONAL_ID,)


def test_contact_details_are_kept_by_default_and_redacted_when_enabled() -> None:
    text = "Write to hr.team@example.com or call +441234567890."
    strict = OutputGuard(redact_contact_details=True)

    assert guard.redact(text).text == text
    result = strict.redact(text)
    assert "example.com" not in result.text and "+441234567890" not in result.text
    assert sorted(result.findings) == [EMAIL, PHONE]


# -- legitimate content stays ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Our password policy requires 12 characters and rotation every 90 days.",
        "The API key must be rotated by the security team.",
        "Order 1234 5678 9012 3456 shipped on 2026-10-31.",  # not Luhn-valid
        "Call extension 4410, room 12-B, invoice INV-2026-0042.",
        "See https://docs.example.com/policies/travel?section=3 for details.",
        "Use `token = get_token()` in your code.",
        "Hotels are reimbursed up to 150 EUR per night [S1].",
    ],
)
def test_ordinary_text_is_untouched(text: str) -> None:
    result = guard.redact(text)

    assert result.text == text
    assert result.findings == ()


def test_a_disabled_guard_changes_nothing() -> None:
    off = OutputGuard(enabled=False)

    assert off.redact(GROQ_KEY).text == GROQ_KEY
    stream = off.stream()
    assert stream.feed(GROQ_KEY[:5]) + stream.feed(GROQ_KEY[5:]) + stream.finish() == GROQ_KEY


def test_already_redacted_text_is_not_redacted_again() -> None:
    once = guard.redact(f"api_key={GROQ_KEY}")

    assert once.findings == (CREDENTIAL,)  # counted once, not twice
    assert guard.redact(once.text).findings == ()


# -- streaming ---------------------------------------------------------------------------------

CORPUS = [
    f"Your key is {GROQ_KEY} and the token is {JWT}. Thanks!",
    f"password = Summer2026xyz\nand then more text after it, plenty of words {AWS_KEY}",
    f"Card number: {CARD} please",
    f"Begin\n{PEM}\nafter the key there is more prose.",
    "Plain prose with no secrets at all, and a citation [S2], and numbers 1 2 3 4.",
    f"Authorization: Bearer {'z' * 30} sent.",
    f"url postgresql://u:{'p' * 10}@h/db and ssn {SSN} end",
    "x" * 2000 + " tail",  # one long token: the hold is bounded
]


def _stream(text: str, cuts: list[int], g: OutputGuard = guard) -> tuple[str, list[str]]:
    stream = g.stream()
    emitted: list[str] = []
    previous = 0
    for cut in [*cuts, len(text)]:
        emitted.append(stream.feed(text[previous:cut]))
        previous = cut
    emitted.append(stream.finish())
    return "".join(emitted), emitted


@pytest.mark.parametrize("text", CORPUS)
def test_streamed_text_equals_the_final_text_for_any_chunking(text: str) -> None:
    expected = guard.redact(text)
    rng = random.Random(len(text))
    for _ in range(60):
        cuts = sorted(rng.sample(range(1, len(text)), k=min(len(text) - 1, rng.randint(1, 25))))
        streamed, _ = _stream(text, cuts)
        assert streamed == expected.text, cuts


@pytest.mark.parametrize("text", CORPUS)
def test_character_by_character_streaming_matches_too(text: str) -> None:
    streamed, _ = _stream(text, list(range(1, len(text))))

    assert streamed == guard.redact(text).text


@pytest.mark.parametrize("secret", [GROQ_KEY, JWT, "Summer2026xyz", CARD, "MIIEowIBAAKCAQEA"])
def test_no_part_of_a_secret_is_ever_sent_before_it_is_recognised(secret: str) -> None:
    text = next(t for t in CORPUS if secret in t)
    prefix = secret[: max(6, len(secret) // 2)]
    stream = guard.stream()
    sent = ""
    for char in text:
        sent += stream.feed(char)
        assert prefix not in sent
    sent += stream.finish()
    assert prefix not in sent


def test_a_long_unbroken_token_does_not_stall_the_stream() -> None:
    stream = guard.stream()

    released = stream.feed("y" * 600)

    assert released  # beyond the bound it is released (still redacted, here nothing to redact)


def test_findings_are_counted_the_same_way_when_streamed() -> None:
    text = CORPUS[0]
    stream = guard.stream()
    for char in text:
        stream.feed(char)
    stream.finish()

    assert stream.findings == guard.redact(text).findings


# -- tool results and logs ---------------------------------------------------------------------


def test_tool_result_data_is_redacted_and_keeps_its_structure() -> None:
    data = {
        "results": [{"content": f"config: api_key={GROQ_KEY}", "similarity": 0.9, "page": 3}],
        "count": 1,
        "nested": ("plain", OPENAI_KEY),
    }

    redacted, findings = guard.redact_data(data)

    serialised = json.dumps(redacted)
    assert GROQ_KEY not in serialised and OPENAI_KEY not in serialised
    assert redacted["results"][0]["similarity"] == 0.9 and redacted["count"] == 1
    assert isinstance(redacted["nested"], tuple)
    assert findings == (CREDENTIAL, CREDENTIAL)


def test_logs_carry_kinds_and_counts_never_values() -> None:
    result = guard.redact(f"{GROQ_KEY} {CARD}")

    with structlog.testing.capture_logs() as logs:
        log_findings("test_output_redacted", result.findings, conversation_id="c1")

    (entry,) = logs
    assert entry["kinds"] == [CARD_NUMBER, CREDENTIAL] and entry["count"] == 2
    assert GROQ_KEY not in repr(logs) and "4111" not in repr(logs)


def test_nothing_found_logs_nothing() -> None:
    with structlog.testing.capture_logs() as logs:
        log_findings("test_output_redacted", ())

    assert logs == []
