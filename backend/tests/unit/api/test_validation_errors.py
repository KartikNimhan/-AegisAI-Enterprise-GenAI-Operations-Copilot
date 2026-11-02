"""A 422 says what is wrong without echoing what was sent.

Regression: the handler returned `str(exc.errors())`, a Python repr that included every rejected
`input` (a 40,000-character message came back in full) and parser internals.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.limits import MAX_MESSAGE_CHARS
from app.main import app

ECHO_PROBE = "PROBE-VALUE-that-must-not-be-echoed"


def post(json: object | None = None, content: bytes | None = None):
    headers = {"content-type": "application/json"} if content is not None else None
    return TestClient(app).post(
        "/api/v1/chat/completions", json=json, content=content, headers=headers
    )


def test_an_oversized_field_is_reported_without_its_value() -> None:
    response = post({"message": ECHO_PROBE + "x" * (MAX_MESSAGE_CHARS + 10)})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert ECHO_PROBE not in response.text
    assert "xxxx" not in response.text
    assert len(response.text) < 1000  # was over 40,000 characters
    assert error["message"] == "body.message: String should have at most 32000 characters"
    assert error["details"] == [
        {
            "loc": ["body", "message"],
            "msg": "String should have at most 32000 characters",
            "type": "string_too_long",
        }
    ]
    assert error["request_id"]


def test_the_details_never_carry_input_or_parser_context() -> None:
    response = post({"message": ECHO_PROBE, "model_role": "not-a-role"})

    assert response.status_code == 422
    for detail in response.json()["error"]["details"]:
        assert set(detail) == {"loc", "msg", "type"}
    assert ECHO_PROBE not in response.text


def test_invalid_json_does_not_leak_parser_internals() -> None:
    response = post(content=b'{"message": "' + ECHO_PROBE.encode() + b'", oops}')

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"][0]["type"] == "json_invalid"
    assert "Expecting" not in response.text  # the json module's own error text was in `ctx`
    assert ECHO_PROBE not in response.text


def test_a_missing_field_reads_well() -> None:
    response = post({})

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "body.message: Field required"


def test_many_errors_are_capped() -> None:
    from app.core.exceptions import _validation_details

    errors = [
        {"loc": ("body", f"f{i}"), "msg": "bad", "type": "x", "input": "v"} for i in range(500)
    ]

    details = _validation_details(errors)

    assert len(details) == 20
    assert all("input" not in d for d in details)


def test_long_user_controlled_locations_are_truncated() -> None:
    from app.core.exceptions import _validation_details

    details = _validation_details(
        [{"loc": ("body", "k" * 10_000), "msg": "m" * 10_000, "type": "t"}]
    )

    assert len(details[0]["loc"][1]) == 64
    assert len(details[0]["msg"]) == 200
