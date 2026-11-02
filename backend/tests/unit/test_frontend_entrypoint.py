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
        "AEGIS_NGINX_CONF_DIR": tmp_path.as_posix(),
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


# -- security headers (AIGSEC-011) --------------------------------------------------------------


def _headers(tmp_path: Path) -> dict[str, str]:
    text = (tmp_path / "aegis-security-headers.conf").read_text(encoding="utf-8")
    values = dict(re.findall(r'map \$host \$(aegis_\w+) \{\n    default "([^"]*)";\n\}', text))
    assert set(values) == {"aegis_csp", "aegis_hsts"}, text
    return values


def _directives(policy: str) -> dict[str, list[str]]:
    parsed = {}
    for part in policy.split(";"):
        name, *sources = part.split()
        parsed[name] = sources
    return parsed


def test_the_policy_allows_only_this_origin_and_the_configured_ones(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        API_BASE_URL="http://localhost:8000",
        OIDC_AUTHORITY="http://localhost:18081/realms/aegisai-demo",
        OIDC_CLIENT_ID="aegisai-web",
    )

    assert result.returncode == 0, result.stderr
    policy = _directives(_headers(tmp_path)["aegis_csp"])
    for name in ("default-src", "script-src", "style-src", "img-src", "font-src"):
        assert policy[name] == ["'self'"], name
    assert policy["connect-src"] == ["'self'", "http://localhost:8000", "http://localhost:18081"]
    assert policy["frame-src"] == ["'self'", "http://localhost:18081"]  # silent renew
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'self'"]
    assert policy["form-action"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'self'"]


def test_the_policy_never_allows_inline_code_eval_or_wildcards(tmp_path: Path) -> None:
    result = _run(tmp_path, OIDC_AUTHORITY="https://idp.example.test/r", OIDC_CLIENT_ID="web")

    assert result.returncode == 0, result.stderr
    policy = _headers(tmp_path)["aegis_csp"]
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    sources = {source for values in _directives(policy).values() for source in values}
    # No wildcard and no whole-scheme source, which would allow any host.
    assert not sources & {"*", "data:", "blob:", "http:", "https:"}
    assert not [source for source in sources if "*" in source]


def test_a_same_origin_api_adds_nothing_to_connect_src(tmp_path: Path) -> None:
    result = _run(tmp_path, API_BASE_URL="", OIDC_AUTHORITY="https://idp.example.test/r/x")

    assert result.returncode == 0, result.stderr
    policy = _directives(_headers(tmp_path)["aegis_csp"])
    assert policy["connect-src"] == ["'self'", "https://idp.example.test"]


def test_without_sign_in_configured_frames_and_connections_stay_same_origin(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, API_BASE_URL="")

    assert result.returncode == 0, result.stderr
    policy = _directives(_headers(tmp_path)["aegis_csp"])
    assert policy["connect-src"] == ["'self'"]
    assert policy["frame-src"] == ["'self'"]


def test_hsts_is_off_unless_asked_for(tmp_path: Path) -> None:
    assert _run(tmp_path).returncode == 0
    assert _headers(tmp_path)["aegis_hsts"] == ""  # nginx then omits the header


def test_hsts_when_asked_for_has_no_subdomain_or_preload_flags(tmp_path: Path) -> None:
    assert _run(tmp_path, HSTS_MAX_AGE="31536000").returncode == 0
    assert _headers(tmp_path)["aegis_hsts"] == "max-age=31536000"


def test_hsts_zero_means_off(tmp_path: Path) -> None:
    assert _run(tmp_path, HSTS_MAX_AGE="0").returncode == 0
    assert _headers(tmp_path)["aegis_hsts"] == ""


@pytest.mark.parametrize("value", ["1y", "-1", "31536000; includeSubDomains", "60 "])
def test_an_invalid_hsts_value_is_refused(tmp_path: Path, value: str) -> None:
    result = _run(tmp_path, HSTS_MAX_AGE=value)

    assert result.returncode != 0
    assert "HSTS_MAX_AGE" in result.stderr
    assert not (tmp_path / "aegis-security-headers.conf").exists()
