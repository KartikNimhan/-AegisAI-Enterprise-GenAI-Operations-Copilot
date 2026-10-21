"""The frontend container's start-up script, run for real (with `sh`) against a
temporary directory: what it writes into config.js, and what it refuses to write.
config.js is JavaScript the browser executes, so unsafe values must be refused,
not escaped."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "frontend" / "web" / "docker-entrypoint.sh"
_SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(_SH is None, reason="needs a POSIX sh")


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    # A minimal environment: only what the script reads, plus PATH for `cat`/`mv`.
    base = {
        "PATH": str(Path(_SH or "").parent) + ":/usr/bin:/bin",
        "AEGIS_HTML_DIR": tmp_path.as_posix(),
    }
    return subprocess.run(
        [_SH or "sh", _SCRIPT.as_posix()],
        env={**base, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _config(tmp_path: Path) -> dict[str, object]:
    """config.js is `window.__AEGIS_CONFIG__ = { ... };` with unquoted keys; read
    the values back with a strict pattern."""
    text = (tmp_path / "config.js").read_text(encoding="utf-8")
    match = re.fullmatch(
        r'window\.__AEGIS_CONFIG__ = \{ apiBaseUrl: ("[^"]*"), oidc: \{ authority: ("[^"]*"), '
        r'clientId: ("[^"]*") \} \};\s*',
        text,
    )
    assert match, text
    api, authority, client_id = (json.loads(group) for group in match.groups())
    return {"apiBaseUrl": api, "authority": authority, "clientId": client_id}


def test_writes_the_runtime_configuration(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        API_BASE_URL="",
        OIDC_AUTHORITY="https://idp.example.test/realms/aegis",
        OIDC_CLIENT_ID="aegisai-web",
    )

    assert result.returncode == 0, result.stderr
    assert _config(tmp_path) == {
        "apiBaseUrl": "",
        "authority": "https://idp.example.test/realms/aegis",
        "clientId": "aegisai-web",
    }
    assert not (tmp_path / "config.js.tmp").exists()  # renamed into place, not left behind


def test_unset_oidc_values_are_written_empty_so_the_ui_reports_sign_in_unconfigured(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)  # nothing set: the script's own defaults apply

    assert result.returncode == 0, result.stderr
    assert _config(tmp_path) == {
        "apiBaseUrl": "http://localhost:8000",
        "authority": "",
        "clientId": "",
    }


def test_it_replaces_a_placeholder_config_js_it_does_not_own(tmp_path: Path) -> None:
    (tmp_path / "config.js").write_text("window.__AEGIS_CONFIG__ = {};", encoding="utf-8")

    result = _run(tmp_path, OIDC_AUTHORITY="https://idp.example.test/r", OIDC_CLIENT_ID="web")

    assert result.returncode == 0, result.stderr
    assert _config(tmp_path)["clientId"] == "web"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OIDC_AUTHORITY", 'https://idp.example.test/";alert(1);//'),
        ("OIDC_AUTHORITY", "https://idp.example.test/realm x"),
        ("OIDC_AUTHORITY", "javascript:alert(1)"),
        ("OIDC_AUTHORITY", "ftp://idp.example.test"),
        ("OIDC_AUTHORITY", "idp.example.test"),
        ("OIDC_CLIENT_ID", 'web";alert(1);//'),
        ("OIDC_CLIENT_ID", "web client"),
        ("API_BASE_URL", 'http://a";x'),
        ("BACKEND_UPSTREAM", "http://h:1/path"),
    ],
)
def test_unsafe_values_are_refused_and_no_config_is_written(
    tmp_path: Path, name: str, value: str
) -> None:
    env = {"OIDC_AUTHORITY": "https://idp.example.test/r", "OIDC_CLIENT_ID": "web", name: value}

    result = _run(tmp_path, **env)

    assert result.returncode != 0
    assert "refusing to start" in result.stderr or "must be" in result.stderr
    assert not (tmp_path / "config.js").exists()
