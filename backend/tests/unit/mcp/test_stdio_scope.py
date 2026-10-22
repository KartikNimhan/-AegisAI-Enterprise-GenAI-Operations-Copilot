"""The stdio MCP server must never start with cross-organization access by accident."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3]
# The scope rules live beside the script (an operator tool), not under app/: the application
# package must never contain the unrestricted scope (tests/unit/auth/test_isolation_structure.py).
sys.path.insert(0, str(BACKEND / "scripts"))

from stdio_scope import (  # type: ignore[import-not-found]  # noqa: E402
    ALLOW_UNRESTRICTED_VAR,
    ORGANIZATION_ID_VAR,
    USER_ID_VAR,
    StdioScopeError,
    resolve_stdio_scope,
)

USER, ORG = str(uuid.uuid4()), str(uuid.uuid4())


def test_nothing_set_refuses_to_start() -> None:
    with pytest.raises(StdioScopeError, match="Refusing to start"):
        resolve_stdio_scope({})


@pytest.mark.parametrize("value", ["", "false", "0", "yes", "1", "TRUEISH", " "])
def test_only_an_explicit_true_enables_unrestricted_access(value: str) -> None:
    with pytest.raises(StdioScopeError):
        resolve_stdio_scope({ALLOW_UNRESTRICTED_VAR: value})


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_an_explicit_opt_in_gives_the_operator_scope(value: str) -> None:
    scope = resolve_stdio_scope({ALLOW_UNRESTRICTED_VAR: value})
    assert scope.unrestricted is True


def test_a_user_and_organization_give_a_scoped_identity() -> None:
    scope = resolve_stdio_scope({USER_ID_VAR: USER, ORGANIZATION_ID_VAR: ORG})

    assert scope.unrestricted is False
    assert str(scope.user_id) == USER and str(scope.organization_id) == ORG
    assert scope.is_admin is False


@pytest.mark.parametrize(
    "environ",
    [
        {USER_ID_VAR: USER},
        {ORGANIZATION_ID_VAR: ORG},
        {USER_ID_VAR: "not-a-uuid", ORGANIZATION_ID_VAR: ORG},
        {USER_ID_VAR: USER, ORGANIZATION_ID_VAR: ""},
    ],
)
def test_a_partial_or_malformed_identity_fails_closed(environ: dict[str, str]) -> None:
    with pytest.raises(StdioScopeError):
        resolve_stdio_scope(environ)


def test_an_identity_together_with_the_unrestricted_flag_is_ambiguous() -> None:
    with pytest.raises(StdioScopeError, match="not both"):
        resolve_stdio_scope(
            {USER_ID_VAR: USER, ORGANIZATION_ID_VAR: ORG, ALLOW_UNRESTRICTED_VAR: "true"}
        )


def test_the_script_exits_with_an_error_and_no_database_access_when_unconfigured() -> None:
    environ = {
        k: v
        for k, v in os.environ.items()
        if k not in {USER_ID_VAR, ORGANIZATION_ID_VAR, ALLOW_UNRESTRICTED_VAR}
    }
    environ["PYTHONPATH"] = str(BACKEND)  # `app` is importable when run from backend/
    done = subprocess.run(  # noqa: S603 - fixed arguments, this interpreter, a repo script
        [sys.executable, "-B", "scripts/mcp_stdio_server.py"],
        cwd=BACKEND,
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 2
    assert "Refusing to start" in done.stderr
