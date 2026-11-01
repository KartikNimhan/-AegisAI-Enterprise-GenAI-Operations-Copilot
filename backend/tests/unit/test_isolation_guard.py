"""The test-isolation guard (`backend/tests/isolation.py`) and the unit-test connection block.

Every test here passes the guard explicit inputs: a dict for the environment and temporary files
standing in for `.env` and `.env.test`. None reads the real `.env` or `.env.test`, and none
connects anywhere (the unit-test block in `tests/unit/conftest.py` would stop it).
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import asyncpg
import pytest
from pydantic_settings.sources.utils import parse_env_vars
from redis.connection import parse_url as parse_redis_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings, get_settings
from app.db import session as session_module
from app.db.session import check_database
from tests import isolation
from tests.isolation import (
    BACKEND_DIR,
    GUARDED_VARIABLES,
    LIVE_LLM_OPT_IN_VAR,
    REPO_ROOT,
    UNCONFIGURED_DATABASE_URL,
    UNCONFIGURED_REDIS_URL,
    IsolationError,
    active_targets,
    alembic_head,
    apply_targets,
    configure_test_process,
    development_database_name,
    development_redis_db,
    ensure_application_not_configured_yet,
    load_targets,
    migration_message,
    read_setting,
    redact,
    redis_database_number,
    remove_case_variants,
    remove_inherited_settings,
    settings_variable_names,
    validate_database_url,
    validate_redis_url,
    wrong_database_message,
)
from tests.unit.conftest import UnitTestDatabaseAccessError

PASSWORD = "s3cret-pw-do-not-print"
GOOD_DATABASE = f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/aegis_test"
GOOD_REDIS = "redis://localhost:6380/15"


@pytest.fixture
def env_files(tmp_path: Path) -> tuple[Path, Path]:
    """`(.env.test, .env)` stand-ins. Neither exists until a test writes it."""
    return tmp_path / ".env.test", tmp_path / ".env"


def _write(path: Path, **values: str) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")


# -- the database URL rules --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        GOOD_DATABASE,
        "postgresql+asyncpg://aegis:pw@127.0.0.1:5432/aegis_test",
        "postgresql+asyncpg://aegis:pw@[::1]:5432/aegis_test",
        "postgresql+asyncpg://aegis@localhost/other_test",
    ],
)
def test_a_local_database_ending_in_test_is_accepted(url: str) -> None:
    assert (validate_database_url(url, development_database="aegis").database or "").endswith(
        "_test"
    )


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (f"postgresql://aegis:{PASSWORD}@localhost/aegis_test", "postgresql\\+asyncpg driver"),
        (f"postgresql+psycopg://aegis:{PASSWORD}@localhost/aegis_test", "driver"),
        ("sqlite+aiosqlite:///aegis_test", "driver"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@db.example.com:5432/aegis_test", "this machine"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@10.0.0.5/aegis_test", "this machine"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/aegis", "must end in '_test'"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@localhost/aegis_testing", "must end in '_test'"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@localhost/test_aegis", "must end in '_test'"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@localhost/AEGIS_TEST", "must end in '_test'"),
        (f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/", "must name a database"),
        (
            f"postgresql+asyncpg://aegis:{PASSWORD}@localhost/aegis_test?host=db.example.com",
            "query parameters",
        ),
        ("not-a-database-url", "not a valid database URL"),
        ("not a database url", "whitespace or control"),
    ],
)
def test_an_unsafe_database_url_is_refused_without_showing_its_password(
    url: str, reason: str
) -> None:
    with pytest.raises(IsolationError, match=reason) as refused:
        validate_database_url(url, development_database="aegis")

    assert PASSWORD not in str(refused.value)


@pytest.mark.parametrize("development", ["aegis_test", "AEGIS_TEST"])
def test_the_development_database_itself_is_refused(development: str) -> None:
    with pytest.raises(IsolationError, match="development database"):
        validate_database_url(GOOD_DATABASE, development_database=development)


# -- F1: the database name allowlist and raw-URL checks ---------------------------------------

_BASE = f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/"


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("aegis%00_test", "percent-encode"),  # NUL: PostgreSQL would read the name as "aegis"
        ("aegis%09_test", "percent-encode"),  # tab
        ("aegis%20_test", "percent-encode"),  # space
        ("aegis%2F_test", "percent-encode"),  # slash
        ("aegis%5Ftest", "percent-encode"),  # an encoded "_": ambiguous spelling
        ("aegis%2500_test", "percent-encode"),  # double encoding
        ("aegis%", "percent-encode"),
        ("aegis\x00_test", "whitespace or control"),  # raw NUL
        ("aegis\t_test", "whitespace or control"),
        ("aegis _test", "whitespace or control"),
        ("aegis_test\n", "whitespace or control"),
        ("aegis\x7f_test", "whitespace or control"),
        ("aegis_test#x", "'#'"),
        ("aegis/_test", "must end in '_test'"),  # a raw slash in the name
        ("aegis_test/extra", "must end in '_test'"),
        ("Aegis_test", "must end in '_test'"),  # upper case
        ("aegis-db_test", "must end in '_test'"),  # hyphen
        ("aegís_test", "must end in '_test'"),  # non-ASCII
        ("1aegis_test", "must end in '_test'"),  # starts with a digit
        ("_test", "must end in '_test'"),
        ("a" * 59 + "_test", "must end in '_test'"),  # 64 characters: PostgreSQL would truncate
    ],
)
def test_an_unsafe_database_name_is_refused_before_any_connection(name: str, reason: str) -> None:
    with pytest.raises(IsolationError, match=reason) as refused:
        validate_database_url(_BASE + name, development_database="aegis")

    assert PASSWORD not in str(refused.value)


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql+asyncpg://aegis:{PASSWORD}@local%68ost:5432/aegis_test",  # encoded host
        f"postgresql+asyncpg://aegis:{PASSWORD}@%6C%6F%63%61%6C%68%6F%73%74/aegis_test",
    ],
)
def test_a_percent_encoded_host_is_refused(url: str) -> None:
    with pytest.raises(IsolationError, match="percent-encode") as refused:
        validate_database_url(url, development_database="aegis")

    assert PASSWORD not in str(refused.value)


def test_an_unencoded_slash_in_the_password_makes_the_url_ambiguous() -> None:
    with pytest.raises(IsolationError, match="ambiguous|not a valid|must end in") as refused:
        validate_database_url(
            "postgresql+asyncpg://aegis:pa/ss@localhost:5432/aegis_test",
            development_database="aegis",
        )

    assert "pa/ss" not in str(refused.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://aegis:p%40ss%2Fw%3Ard@localhost:5432/aegis_test",  # encoded password
        "postgresql+asyncpg://aegis@localhost/" + "a" * 58 + "_test",  # exactly 63 characters
        "postgresql+asyncpg://aegis@localhost/aegis_2026_test",
    ],
)
def test_a_well_formed_test_database_url_is_still_accepted(url: str) -> None:
    assert validate_database_url(url, development_database="aegis")


# -- F3: case variants of the guarded variables -----------------------------------------------


def test_case_variants_of_the_guarded_variables_are_removed() -> None:
    environ = {
        "DATABASE_URL": "upper",
        "database_url": "lower",
        "Redis_Url": "mixed",
        "groq_api_key": "lower-key",
        "Groq_Api_Key": "mixed-key",
        "TEST_DATABASE_URL": "kept",
        "OTHER": "kept",
    }

    removed = remove_case_variants(environ)

    assert sorted(removed) == ["Groq_Api_Key", "Redis_Url", "database_url", "groq_api_key"]
    assert sorted(environ) == ["DATABASE_URL", "OTHER", "TEST_DATABASE_URL"]


def test_after_applying_the_settings_see_only_the_guarded_values(
    env_files: tuple[Path, Path],
) -> None:
    test_env, dev_env = env_files
    targets = load_targets({}, test_env_file=test_env, dev_env_file=dev_env)
    # The order that used to win: the lower-case spelling after the upper-case one.
    environ = {
        "DATABASE_URL": "postgresql+asyncpg://dev:pw@localhost:5432/aegis",
        "database_url": "postgresql+asyncpg://dev:pw@localhost:5432/aegis",
        "redis_url": "redis://localhost:6380/0",
        "groq_api_key": "a-key-that-must-not-reach-the-tests",
    }

    apply_targets(targets, environ)
    seen = parse_env_vars(environ)  # how the application's settings read the environment

    assert seen["database_url"] == UNCONFIGURED_DATABASE_URL
    assert seen["redis_url"] == UNCONFIGURED_REDIS_URL
    assert seen["groq_api_key"] == ""
    assert seen["debug"] == "false"
    assert set(environ) == {"DATABASE_URL", "REDIS_URL", "GROQ_API_KEY", "DEBUG"}


def test_with_the_opt_in_the_upper_case_groq_key_is_kept_and_its_variants_dropped() -> None:
    environ = {
        "GROQ_API_KEY": "set-on-purpose",
        "groq_api_key": "other",
        LIVE_LLM_OPT_IN_VAR: "1",
    }

    apply_targets(
        load_targets({}, test_env_file=Path("missing"), dev_env_file=Path("missing")), environ
    )

    assert environ["GROQ_API_KEY"] == "set-on-purpose"
    assert "groq_api_key" not in environ


def test_this_process_has_no_case_variants_left() -> None:
    assert [k for k in os.environ if k.upper() in GUARDED_VARIABLES and k != k.upper()] == []


def test_configuring_twice_returns_the_first_result() -> None:
    assert configure_test_process() is active_targets()


# -- the Redis URL rules -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "number"),
    [(GOOD_REDIS, 15), ("rediss://localhost:6380/3", 3), ("redis://[::1]:6379/9", 9)],
)
def test_a_local_redis_with_another_number_is_accepted(url: str, number: int) -> None:
    assert validate_redis_url(url, development_redis_db=0) == number


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://localhost:6380/15", "redis:// or rediss://"),
        ("redis://cache.example.com:6379/15", "this machine"),
        ("redis://localhost:6380/0", "same number"),
        ("redis://localhost:6380", "same number"),  # no number means database 0
        ("redis://localhost:6380/15?db=0", "query parameters"),
        ("redis://localhost:6380/abc", "invalid database number"),
    ],
)
def test_an_unsafe_redis_url_is_refused(url: str, reason: str) -> None:
    with pytest.raises(IsolationError, match=reason):
        validate_redis_url(url, development_redis_db=0)


# -- F4: the development Redis number is read the way redis-py reads it ------------------------


@pytest.mark.parametrize(
    ("url", "number"),
    [
        ("redis://localhost:6380", 0),
        ("redis://localhost:6380/", 0),
        ("redis://localhost:6380/3", 3),
        ("redis://localhost:6380?db=5", 5),
        ("redis://localhost:6380/?db=5", 5),
        ("redis://localhost:6380/5?db=5", 5),  # path and query agree
        ("rediss://localhost:6380/7", 7),
        ("unix:///tmp/redis.sock?db=4", 4),
    ],
)
def test_the_redis_number_matches_redis_py(url: str, number: int) -> None:
    assert redis_database_number(url) == number
    assert int(parse_redis_url(url).get("db", 0)) == number  # redis-py's own reading


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("redis://localhost:6380/2?db=3", "different databases"),
        ("redis://localhost:6380?db=1&db=2", "more than once"),
        ("redis://localhost:6380?db=x", "malformed"),
        ("redis://localhost:6380/abc", "malformed"),
        ("http://localhost:6380/1", "malformed"),
        ("", "malformed"),
    ],
)
def test_a_malformed_or_ambiguous_redis_url_is_refused(url: str, reason: str) -> None:
    with pytest.raises(IsolationError, match=reason):
        redis_database_number(url)


@pytest.mark.parametrize(
    ("dev_redis_url", "test_redis_url", "accepted"),
    [
        ("redis://localhost:6380/15", "redis://localhost:6380/15", False),  # path, same number
        ("redis://localhost:6380?db=15", "redis://localhost:6380/15", False),  # query, same
        ("redis://localhost:6380/?db=15", "redis://localhost:6380/15", False),
        ("redis://localhost:6380?db=3", "redis://localhost:6380/15", True),  # query, other
        ("redis://localhost:6380/3", "redis://localhost:6380/15", True),  # path, other
        ("unix:///tmp/redis.sock?db=15", "redis://localhost:6380/15", False),
    ],
)
def test_path_and_query_development_numbers_are_both_respected(
    env_files: tuple[Path, Path], dev_redis_url: str, test_redis_url: str, accepted: bool
) -> None:
    test_env, dev_env = env_files
    _write(dev_env, REDIS_URL=dev_redis_url)

    def load() -> object:
        return load_targets(
            {"TEST_REDIS_URL": test_redis_url}, test_env_file=test_env, dev_env_file=dev_env
        )

    if accepted:
        assert load()
    else:
        with pytest.raises(IsolationError, match="same number"):
            load()


@pytest.mark.parametrize(
    "dev_redis_url",
    [
        "redis://localhost:6380/abc",
        "redis://localhost:6380?db=x",
        "redis://localhost:6380/2?db=3",
        "redis://localhost:6380?db=1&db=2",
        "http://localhost:6380/1",
    ],
)
def test_an_unreadable_development_redis_number_fails_closed(
    env_files: tuple[Path, Path], dev_redis_url: str
) -> None:
    test_env, dev_env = env_files
    _write(dev_env, REDIS_URL=dev_redis_url)

    with pytest.raises(IsolationError, match="Cannot tell which Redis database") as refused:
        load_targets({"TEST_REDIS_URL": GOOD_REDIS}, test_env_file=test_env, dev_env_file=dev_env)
    assert dev_redis_url not in str(refused.value)  # the message never repeats the URL


def test_an_unreadable_development_redis_number_matters_only_with_a_test_redis(
    env_files: tuple[Path, Path],
) -> None:
    test_env, dev_env = env_files
    _write(dev_env, REDIS_URL="redis://localhost:6380/abc")

    targets = load_targets({}, test_env_file=test_env, dev_env_file=dev_env)

    assert targets.redis_url == UNCONFIGURED_REDIS_URL


# -- where the settings come from ----------------------------------------------------------------


def test_the_environment_wins_over_the_test_env_file(env_files: tuple[Path, Path]) -> None:
    test_env, _ = env_files
    _write(test_env, TEST_DATABASE_URL="from-file")

    assert read_setting("TEST_DATABASE_URL", {"TEST_DATABASE_URL": " from-env "}, test_env) == (
        "from-env",
        "environment",
    )


@pytest.mark.parametrize("environment_value", [None, "", "   "])
def test_the_test_env_file_is_used_when_the_environment_has_no_value(
    env_files: tuple[Path, Path], environment_value: str | None
) -> None:
    test_env, _ = env_files
    _write(test_env, TEST_DATABASE_URL="from-file")
    environ = {} if environment_value is None else {"TEST_DATABASE_URL": environment_value}

    assert read_setting("TEST_DATABASE_URL", environ, test_env) == ("from-file", ".env.test")


def test_a_missing_or_empty_setting_is_not_configured(env_files: tuple[Path, Path]) -> None:
    test_env, _ = env_files
    assert read_setting("TEST_DATABASE_URL", {}, test_env) == (None, "not configured")

    _write(test_env, TEST_DATABASE_URL="")
    assert read_setting("TEST_DATABASE_URL", {}, test_env) == (None, "not configured")


def test_the_development_names_come_from_dot_env(env_files: tuple[Path, Path]) -> None:
    _, dev_env = env_files
    _write(
        dev_env,
        DATABASE_URL=f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/aegis_dev",
        REDIS_URL="redis://localhost:6380/3",
    )

    assert development_database_name(dev_env) == "aegis_dev"
    assert development_redis_db(dev_env) == 3


@pytest.mark.parametrize("dev_contents", [None, "DATABASE_URL=\nREDIS_URL=\n"])
def test_without_dot_env_values_the_application_defaults_are_the_development_names(
    env_files: tuple[Path, Path], dev_contents: str | None
) -> None:
    _, dev_env = env_files
    if dev_contents is not None:
        dev_env.write_text(dev_contents, encoding="utf-8")

    assert development_database_name(dev_env) == "aegis"
    assert development_redis_db(dev_env) == 0


# -- loading and applying ------------------------------------------------------------------------


def test_with_nothing_configured_the_placeholders_are_used_and_dot_env_is_not_read(
    env_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    test_env, dev_env = env_files
    _write(dev_env, DATABASE_URL="postgresql+asyncpg://aegis:pw@localhost/aegis")
    read: list[Path] = []
    real = isolation.dotenv_values
    monkeypatch.setattr(isolation, "dotenv_values", lambda path: read.append(path) or real(path))

    targets = load_targets({}, test_env_file=test_env, dev_env_file=dev_env)

    assert targets.database_url == UNCONFIGURED_DATABASE_URL
    assert targets.redis_url == UNCONFIGURED_REDIS_URL
    assert (targets.database_configured, targets.redis_configured) == (False, False)
    assert dev_env not in read


def test_the_placeholders_obey_the_same_rules() -> None:
    assert validate_database_url(UNCONFIGURED_DATABASE_URL, development_database="aegis")
    assert validate_redis_url(UNCONFIGURED_REDIS_URL, development_redis_db=0) == 15


def test_configured_targets_are_validated_and_reported(env_files: tuple[Path, Path]) -> None:
    test_env, dev_env = env_files
    _write(test_env, TEST_DATABASE_URL=GOOD_DATABASE, TEST_REDIS_URL=GOOD_REDIS)

    targets = load_targets({}, test_env_file=test_env, dev_env_file=dev_env)

    assert targets.database_url == GOOD_DATABASE
    assert targets.database_name == "aegis_test"
    assert targets.redis_url == GOOD_REDIS
    assert (targets.database_source, targets.redis_source) == (".env.test", ".env.test")
    assert PASSWORD not in targets.describe()
    assert "aegis_test" in targets.describe()


def test_a_test_database_matching_dot_env_is_refused(env_files: tuple[Path, Path]) -> None:
    test_env, dev_env = env_files
    _write(dev_env, DATABASE_URL="postgresql+asyncpg://aegis:pw@localhost:5432/aegis_test")
    _write(test_env, TEST_DATABASE_URL=GOOD_DATABASE)

    with pytest.raises(IsolationError, match="development database"):
        load_targets({}, test_env_file=test_env, dev_env_file=dev_env)


def test_a_test_redis_matching_dot_env_is_refused(env_files: tuple[Path, Path]) -> None:
    test_env, dev_env = env_files
    _write(dev_env, REDIS_URL="redis://localhost:6380/15")

    with pytest.raises(IsolationError, match="same number"):
        load_targets({"TEST_REDIS_URL": GOOD_REDIS}, test_env_file=test_env, dev_env_file=dev_env)


def test_applying_points_the_application_settings_at_the_targets(
    env_files: tuple[Path, Path],
) -> None:
    test_env, dev_env = env_files
    targets = load_targets(
        {"TEST_DATABASE_URL": GOOD_DATABASE}, test_env_file=test_env, dev_env_file=dev_env
    )
    environ = {"DATABASE_URL": "postgresql+asyncpg://aegis:pw@localhost/aegis"}

    apply_targets(targets, environ)

    assert environ["DATABASE_URL"] == GOOD_DATABASE
    assert environ["REDIS_URL"] == UNCONFIGURED_REDIS_URL
    assert environ["GROQ_API_KEY"] == ""  # a key in .env cannot reach the tests
    assert environ["DEBUG"] == "false"


# -- inherited settings and the two-part Groq opt-in ------------------------------------------

_NO_TARGETS = {"test_env_file": Path("missing"), "dev_env_file": Path("missing")}


def test_an_inherited_groq_key_is_blanked_without_the_opt_in() -> None:
    environ = {"GROQ_API_KEY": "inherited-from-a-terminal"}

    apply_targets(load_targets({}, **_NO_TARGETS), environ)

    assert environ["GROQ_API_KEY"] == ""


@pytest.mark.parametrize("flag", ["", "0", "true", "yes", "1 ", " 1", "2"])
def test_only_the_exact_value_1_opts_in(flag: str) -> None:
    environ = {"GROQ_API_KEY": "inherited", LIVE_LLM_OPT_IN_VAR: flag}

    apply_targets(load_targets({}, **_NO_TARGETS), environ)

    # " 1" and "1 " are accepted after stripping; anything else is not an opt-in.
    expected = "inherited" if flag.strip() == "1" else ""
    assert environ["GROQ_API_KEY"] == expected


def test_with_the_opt_in_but_no_key_the_key_stays_empty() -> None:
    environ = {LIVE_LLM_OPT_IN_VAR: "1"}

    apply_targets(load_targets({}, **_NO_TARGETS), environ)

    assert environ["GROQ_API_KEY"] == ""


def test_every_inherited_application_setting_is_removed_in_any_spelling() -> None:
    names = settings_variable_names()
    environ = {name: "inherited" for name in names}
    environ.update({name.lower(): "inherited" for name in list(names)[:5]})
    environ.update({"Debug": "true", "Environment": "production"})
    controls = {
        "TEST_DATABASE_URL": "kept",
        "TEST_REDIS_URL": "kept",
        "RUN_EMBEDDING_INTEGRATION": "kept",
        "AEGIS_REQUIRE_SERVICES": "kept",
        "PATH": "kept",
        "HF_HUB_OFFLINE": "kept",
    }
    environ.update(controls)

    removed = remove_inherited_settings(environ)

    assert all(key.upper() in names for key in removed)  # names only, never values
    assert environ == controls


def test_the_settings_variable_names_are_the_application_settings_only() -> None:
    names = settings_variable_names()

    assert {"DATABASE_URL", "REDIS_URL", "DEBUG", "ENVIRONMENT", "GROQ_API_KEY"} <= names
    assert not {"TEST_DATABASE_URL", "TEST_REDIS_URL", LIVE_LLM_OPT_IN_VAR} & names
    assert not any(name.startswith(("RUN_", "AEGIS_")) for name in names)


def test_inherited_development_settings_do_not_survive_applying(
    env_files: tuple[Path, Path],
) -> None:
    test_env, dev_env = env_files
    environ = {
        "DEBUG": "true",
        "ENVIRONMENT": "production",
        "AUTH_ISSUER": "https://idp.example.test/realms/dev",
        "groq_api_key": "inherited",
    }

    apply_targets(load_targets({}, test_env_file=test_env, dev_env_file=dev_env), environ)
    seen = parse_env_vars(environ)

    assert seen["debug"] == "false"
    assert "environment" not in seen and "auth_issuer" not in seen
    assert seen["groq_api_key"] == ""


def test_this_process_does_not_read_dot_env_and_runs_without_debug() -> None:
    settings = get_settings()

    assert Settings.model_config.get("env_file") is None
    assert settings.debug is False
    assert settings.sql_echo is False
    if not isolation.live_llm_tests_allowed(os.environ):
        assert settings.has_groq_api_key is False


@pytest.mark.parametrize(
    "module", ["tests.integration.test_groq_live", "tests.integration.test_agent_live"]
)
def test_the_key_only_live_tests_are_skipped_without_the_opt_in(module: str) -> None:
    # These two are gated on GROQ_API_KEY alone. Importing them evaluates their skip condition
    # with this process's (sanitized) environment; nothing runs and nothing is called.
    if isolation.live_llm_tests_allowed(os.environ):
        pytest.skip("AEGIS_ALLOW_LIVE_LLM_TESTS=1 is set: the live tests are meant to run")
    marks = importlib.import_module(module).pytestmark
    gates = [
        mark
        for mark in marks
        if mark.name == "skipif" and "GROQ_API_KEY" in str(mark.kwargs.get("reason", ""))
    ]

    assert gates and all(mark.args[0] is True for mark in gates)


def test_redact_hides_the_password() -> None:
    assert PASSWORD not in redact(GOOD_DATABASE)
    assert "aegis_test" in redact(GOOD_DATABASE)
    assert redact("::not a url::") == "<unparsable URL>"


# -- this test process ---------------------------------------------------------------------------


def test_this_process_uses_only_a_test_database() -> None:
    targets = active_targets()

    assert get_settings().database_url == targets.database_url
    assert get_settings().redis_url == targets.redis_url
    assert targets.database_name.endswith("_test")
    assert (session_module.engine.url.database or "").endswith("_test")


def test_the_guard_refuses_once_the_application_is_already_loaded() -> None:
    with pytest.raises(IsolationError, match="imported before the test isolation guard"):
        ensure_application_not_configured_yet()


def test_the_guard_runs_before_the_first_application_import() -> None:
    tree = ast.parse((BACKEND_DIR / "tests" / "conftest.py").read_text(encoding="utf-8"))
    guard_line = next(
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", None) == "configure_test_process"
    )
    app_imports = [
        node.lineno
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "app"
    ]

    assert app_imports and guard_line < min(app_imports)


# -- the unit-test connection block ---------------------------------------------------------------


async def test_unit_tests_cannot_open_an_asyncpg_connection() -> None:
    with pytest.raises(UnitTestDatabaseAccessError):
        await asyncpg.connect("postgresql://aegis@127.0.0.1:1/blocked_test")


async def test_unit_tests_cannot_connect_through_sqlalchemy() -> None:
    engine = create_async_engine(UNCONFIGURED_DATABASE_URL)
    try:
        with pytest.raises(UnitTestDatabaseAccessError):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()


async def test_the_readiness_check_reports_the_blocked_database_as_down() -> None:
    assert await check_database(timeout=2.0) is False


# -- the live checks --------------------------------------------------------------------------


def test_the_server_must_report_the_configured_test_database() -> None:
    assert wrong_database_message(expected="aegis_test", actual="aegis_test") is None
    for actual in ("aegis", None, "other_test"):
        message = wrong_database_message(expected="aegis_test", actual=actual)
        assert message is not None and "Stopping" in message


def test_the_test_database_must_be_at_the_code_migration() -> None:
    assert migration_message(database="aegis_test", revision="0008", head="0008") is None
    unmigrated = migration_message(database="aegis_test", revision=None, head="0008")
    behind = migration_message(database="aegis_test", revision="0007", head="0008")

    assert unmigrated is not None and "no migrations applied" in unmigrated
    assert behind is not None and "revision 0007" in behind
    assert "scripts/test_db.py migrate --yes" in behind


def test_the_alembic_head_is_read_from_the_migration_files() -> None:
    head = alembic_head()

    assert list((BACKEND_DIR / "alembic" / "versions").glob(f"{head}_*.py"))


# -- the template and Git ignore rules ---------------------------------------------------------


def test_the_template_passes_the_guard_and_holds_no_password(env_files: tuple[Path, Path]) -> None:
    _, dev_env = env_files
    template = REPO_ROOT / ".env.test.example"

    targets = load_targets({}, test_env_file=template, dev_env_file=dev_env)

    assert targets.database_name == "aegis_test"
    assert targets.redis_configured
    assert ":CHANGE_ME@" in targets.database_url


def test_git_ignores_dot_env_test_but_not_its_template() -> None:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env.*" in lines
    assert "!.env.test.example" in lines


# -- scripts/test_db.py --------------------------------------------------------------------------


def _load_script() -> ModuleType:
    path = REPO_ROOT / "scripts" / "test_db.py"
    spec = importlib.util.spec_from_file_location("aegis_test_db_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while building the class
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


def _status(script: ModuleType, **overrides: Any) -> Any:
    values = {
        "current_database": "aegis_test",
        "server_version": "18.0",
        "vector_installed": True,
        "revision": alembic_head(),
    }
    values.update(overrides)
    return script.DatabaseStatus(**values)


def _fake_reads(monkeypatch: pytest.MonkeyPatch, script: ModuleType, *statuses: Any) -> list[str]:
    urls: list[str] = []
    queue = list(statuses)

    async def read_status(url: str) -> Any:
        urls.append(url)
        result = queue.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(script, "read_status", read_status)
    return urls


def _run(script: ModuleType, env_files: tuple[Path, Path], argv: list[str], **environ: str) -> int:
    test_env, dev_env = env_files
    return script.main(argv, environ=environ, test_env_file=test_env, dev_env_file=dev_env)


def test_the_script_does_nothing_without_a_configured_test_database(
    script: ModuleType, env_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(script, env_files, ["check"]) == script.EXIT_REFUSED
    assert ".env.test.example" in capsys.readouterr().out


def test_the_script_refuses_the_development_database_before_connecting(
    script: ModuleType, env_files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    development = f"postgresql+asyncpg://aegis:{PASSWORD}@localhost:5432/aegis"

    assert _run(script, env_files, ["check"], TEST_DATABASE_URL=development) == script.EXIT_REFUSED
    output = capsys.readouterr().out
    assert "_test" in output and PASSWORD not in output


def test_migrate_needs_yes(
    script: ModuleType,
    env_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    urls = _fake_reads(monkeypatch, script)

    assert (
        _run(script, env_files, ["migrate"], TEST_DATABASE_URL=GOOD_DATABASE) == script.EXIT_REFUSED
    )
    assert urls == []  # it did not even connect
    assert "--yes" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status_overrides", "expected"),
    [
        ({}, "EXIT_READY"),
        ({"revision": None}, "EXIT_NOT_READY"),
        ({"revision": "0001"}, "EXIT_NOT_READY"),
        ({"vector_installed": False}, "EXIT_NOT_READY"),
        ({"current_database": "aegis"}, "EXIT_UNREACHABLE"),
    ],
)
def test_check_reports_the_state_without_showing_the_password(
    script: ModuleType,
    env_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status_overrides: dict[str, Any],
    expected: str,
) -> None:
    urls = _fake_reads(monkeypatch, script, _status(script, **status_overrides))

    code = _run(script, env_files, ["check"], TEST_DATABASE_URL=GOOD_DATABASE)

    assert code == getattr(script, expected)
    assert urls == [GOOD_DATABASE]
    assert PASSWORD not in capsys.readouterr().out


def test_check_reports_an_unreachable_server(
    script: ModuleType, env_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_reads(monkeypatch, script, ConnectionRefusedError())

    assert _run(script, env_files, ["check"], TEST_DATABASE_URL=GOOD_DATABASE) == (
        script.EXIT_UNREACHABLE
    )


def test_migrate_upgrades_only_the_confirmed_test_database(
    script: ModuleType, env_files: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_reads(monkeypatch, script, _status(script, revision=None), _status(script))
    upgraded: list[str] = []
    monkeypatch.setattr(script, "_run_alembic_upgrade", lambda url: upgraded.append(url) or 0)

    code = _run(script, env_files, ["migrate", "--yes"], TEST_DATABASE_URL=GOOD_DATABASE)

    assert code == script.EXIT_READY
    assert upgraded == [GOOD_DATABASE]


@pytest.mark.parametrize(
    "status_overrides", [{"current_database": "aegis"}, {"vector_installed": False}]
)
def test_migrate_refuses_a_wrong_or_unprepared_database(
    script: ModuleType,
    env_files: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    status_overrides: dict[str, Any],
) -> None:
    _fake_reads(monkeypatch, script, _status(script, revision=None, **status_overrides))
    upgraded: list[str] = []
    monkeypatch.setattr(script, "_run_alembic_upgrade", lambda url: upgraded.append(url) or 0)

    code = _run(script, env_files, ["migrate", "--yes"], TEST_DATABASE_URL=GOOD_DATABASE)

    assert code != script.EXIT_READY
    assert upgraded == []
