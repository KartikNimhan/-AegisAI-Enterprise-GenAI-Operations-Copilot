"""Keeps every test run away from the development database.

`configure_test_process()` runs when pytest first imports the `tests` package
(`backend/tests/__init__.py`), before anything imports the application. Every test module and
every conftest belongs to that package, so this happens with `--noconftest`, with any
`--confcutdir` and in every `--import-mode`; `backend/tests/conftest.py` calls it again, which is
a no-op. It decides which PostgreSQL database and Redis database this pytest process may use,
refuses anything unsafe, and then prepares the application's settings for this process only:

- `app.config.Settings` stops reading `.env` (`disable_dotenv`);
- every inherited variable named after an application setting is removed, in any spelling, so an
  editor or shell that copied `.env` into the terminal cannot reach the tests;
- `DATABASE_URL` and `REDIS_URL` point at the validated test targets and `DEBUG` is `false`;
- `GROQ_API_KEY` is empty unless `AEGIS_ALLOW_LIVE_LLM_TESTS=1` is set alongside it, so the billed
  live tests run only on an explicit two-part opt-in.

The shell, `.env` and `.env.test` are never modified.

Where the test targets come from, first match wins:

1. `TEST_DATABASE_URL` / `TEST_REDIS_URL` in the environment (CI sets them);
2. the same names in `.env.test` at the repository root (ignored by Git; copy
   `.env.test.example`).

A test database is accepted only when its URL

- contains no whitespace, control characters or `#`,
- uses the `postgresql+asyncpg` driver,
- points at this machine (`localhost`, `127.0.0.1` or `::1`),
- has no query parameters (they could redirect the connection elsewhere),
- writes the host and database name without percent-encoding (`%00`, `%2F`, ... are refused),
- names a database of lowercase letters, digits and underscores, starting with a letter, ending
  in `_test`, at most 63 characters, and
- does not name the same database as `DATABASE_URL` in `.env` (or the application default).

A test Redis is accepted only when it is on this machine, has no query parameters, and uses a
different Redis database number from `REDIS_URL` in `.env`, read the way redis-py reads it (a
`?db=` query wins over the path). If that development number cannot be read with certainty, the
test Redis is refused.

With no test database configured, the process gets an address where nothing listens, so
integration tests skip (or fail, under `AEGIS_REQUIRE_SERVICES=1`) instead of reaching a real
database. `.env` is read only to learn the development database's name and Redis number, and only
when a test target is configured; nothing here prints a password.

The integration and evaluation database fixtures add a live check on top
(`backend/tests/live_database.py`): the server must report the expected `_test` database at the
expected Alembic revision before any test touches it.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values
from redis.connection import parse_url as parse_redis_url
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
TEST_ENV_FILE = REPO_ROOT / ".env.test"
DEV_ENV_FILE = REPO_ROOT / ".env"

TEST_DATABASE_URL_VAR = "TEST_DATABASE_URL"
TEST_REDIS_URL_VAR = "TEST_REDIS_URL"
REQUIRED_DATABASE_SUFFIX = "_test"
REQUIRED_DRIVER = "postgresql+asyncpg"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
ALLOWED_REDIS_SCHEMES = frozenset({"redis", "rediss"})
# A test database name: lowercase ASCII letters, digits and underscores, starting with a letter,
# ending in `_test`, and at most 63 characters (PostgreSQL silently truncates longer names, which
# could cut the `_test` suffix off).
DATABASE_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*_test")
MAX_DATABASE_NAME_LENGTH = 63
_CONTROL_OR_WHITESPACE = re.compile(r"[\x00-\x20\x7f-\x9f]")
# The application settings the guard replaces, and must win for, in the test process.
GUARDED_VARIABLES = ("DATABASE_URL", "REDIS_URL", "GROQ_API_KEY")
# The second half of the opt-in for billed live Groq tests (the first is GROQ_API_KEY itself).
LIVE_LLM_OPT_IN_VAR = "AEGIS_ALLOW_LIVE_LLM_TESTS"

# Nothing listens on port 1, so a connection is refused at once. The names still follow the
# `_test` rule, so even this placeholder could never be mistaken for a real database.
UNCONFIGURED_DATABASE_URL = (
    "postgresql+asyncpg://aegis_tests:not-a-password@127.0.0.1:1/aegis_unconfigured_test"
)
UNCONFIGURED_REDIS_URL = "redis://127.0.0.1:1/15"

NOT_CONFIGURED = "not configured"
MIGRATE_COMMAND = "uv run python scripts/test_db.py migrate --yes"


class IsolationError(RuntimeError):
    """A test-target setting that would be unsafe to use. Messages never contain a password."""


@dataclass(frozen=True)
class IsolationTargets:
    """What this test process may connect to, and where each value came from."""

    database_url: str
    redis_url: str
    database_configured: bool
    redis_configured: bool
    database_source: str
    redis_source: str

    @property
    def database_name(self) -> str:
        return make_url(self.database_url).database or ""

    def describe(self) -> str:
        """A one-line summary that is safe to print (passwords hidden)."""
        database = (
            f"{redact(self.database_url)} (from {self.database_source})"
            if self.database_configured
            else NOT_CONFIGURED
        )
        redis = (
            f"{redact(self.redis_url)} (from {self.redis_source})"
            if self.redis_configured
            else NOT_CONFIGURED
        )
        return f"test database: {database}; test Redis: {redis}"


def redact(url: str) -> str:
    """The URL with any password replaced by `***`, or a fixed text if it cannot be parsed."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "<unparsable URL>"


def read_setting(name: str, environ: Mapping[str, str], env_file: Path) -> tuple[str | None, str]:
    """`(value, source)` for a test setting: the environment first, then `env_file`. An empty
    value counts as unset."""
    value = environ.get(name)
    if value is not None and value.strip():
        return value.strip(), "environment"
    if env_file.is_file():
        file_value = dotenv_values(env_file).get(name)
        if file_value is not None and file_value.strip():
            return file_value.strip(), env_file.name
    return None, NOT_CONFIGURED


def _development_value(name: str, dev_env_file: Path) -> str:
    """`name` as the application sees it in development: from `.env`, else the default in
    `app.config.Settings`."""
    value: str | None = None
    if dev_env_file.is_file():
        value = dotenv_values(dev_env_file).get(name)
    if not value or not value.strip():
        value = str(Settings.model_fields[name.lower()].default)
    return value.strip()


def development_database_name(dev_env_file: Path = DEV_ENV_FILE) -> str:
    """The name of the database the application uses in development (never the password)."""
    try:
        return make_url(_development_value("DATABASE_URL", dev_env_file)).database or ""
    except (ArgumentError, ValueError):
        return ""


def redis_database_number(url: str) -> int:
    """The Redis database number redis-py itself would select for `url` (the application's Redis
    client uses redis-py's own URL parsing): `?db=` wins over the path, and no number means 0.

    Raises `IsolationError` when the URL is malformed, or ambiguous: `?db=` given more than once,
    or a path number that disagrees with `?db=`. Messages never contain the URL."""
    try:
        parts = urlsplit(url)
        options = parse_redis_url(url)
        number = int(options.get("db", 0))
    except (ValueError, TypeError):
        raise IsolationError("the Redis URL is malformed") from None

    query_numbers = parse_qs(parts.query).get("db", [])
    if len(query_numbers) > 1:
        raise IsolationError("the Redis URL sets ?db= more than once")
    path = parts.path.strip("/")
    if parts.scheme in ALLOWED_REDIS_SCHEMES and path and not path.isdigit():
        # redis-py silently ignores a non-numeric path and uses database 0; refuse instead.
        raise IsolationError("the Redis URL is malformed (its path is not a database number)")
    if query_numbers and parts.scheme in ALLOWED_REDIS_SCHEMES and path and path != str(number):
        raise IsolationError("the Redis URL's path and ?db= name different databases")
    return number


def development_redis_db(dev_env_file: Path = DEV_ENV_FILE) -> int:
    """The Redis database number the application uses in development. Fails closed: a malformed or
    ambiguous `REDIS_URL` in `.env` raises `IsolationError` instead of allowing any number."""
    try:
        return redis_database_number(_development_value("REDIS_URL", dev_env_file))
    except IsolationError as exc:
        raise IsolationError(
            f"Cannot tell which Redis database REDIS_URL in .env uses ({exc}), so no test Redis "
            "database can be shown to be separate from it. Fix REDIS_URL in .env, or leave "
            f"{TEST_REDIS_URL_VAR} unset."
        ) from None


def _is_loopback(host: str | None) -> bool:
    return (host or "").strip("[]").lower() in LOOPBACK_HOSTS


def _check_raw_database_url(url: str) -> str:
    """Checks the URL text before any decoding. Returns the database name as written in it.

    Whitespace and control characters are refused anywhere. Percent-encoding is refused in the
    host and in the database name, so a name like `aegis%00_test` (which decodes to a NUL byte that
    PostgreSQL would read as the end of the name) cannot slip through. Passwords may still be
    percent-encoded."""
    if _CONTROL_OR_WHITESPACE.search(url):
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} must not contain whitespace or control characters."
        )
    try:
        parts = urlsplit(url)
    except ValueError:
        raise IsolationError(f"{TEST_DATABASE_URL_VAR} is not a valid database URL.") from None
    if parts.fragment or "#" in url:
        raise IsolationError(f"{TEST_DATABASE_URL_VAR} must not contain '#'.")
    host_and_port = parts.netloc.rpartition("@")[2]
    raw_name = parts.path[1:] if parts.path.startswith("/") else parts.path
    if "%" in host_and_port or "%" in raw_name:
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} must not percent-encode the host or the database name: "
            "write them as plain text."
        )
    return raw_name


def validate_database_url(url: str, *, development_database: str) -> URL:
    """Returns the parsed URL, or raises `IsolationError` saying exactly which rule failed. Runs
    before any connection is opened; nothing here contacts a server."""
    raw_name = _check_raw_database_url(url)
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):
        raise IsolationError(f"{TEST_DATABASE_URL_VAR} is not a valid database URL.") from None

    if parsed.drivername != REQUIRED_DRIVER:
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} must use the {REQUIRED_DRIVER} driver "
            f"(got {parsed.drivername!r})."
        )
    if not _is_loopback(parsed.host):
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} must point at this machine (localhost, 127.0.0.1 or ::1), "
            f"not {parsed.host!r}."
        )
    if parsed.query:
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} must not have query parameters "
            f"(got {sorted(parsed.query)}): they can redirect the connection to another server "
            "or database."
        )
    name = parsed.database or ""
    if not name:
        raise IsolationError(f"{TEST_DATABASE_URL_VAR} must name a database.")
    if name != raw_name:
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} is ambiguous: its database name does not read the same "
            "before and after URL parsing."
        )
    if len(name) > MAX_DATABASE_NAME_LENGTH or not DATABASE_NAME_PATTERN.fullmatch(name):
        raise IsolationError(
            f"The test database name must end in {REQUIRED_DATABASE_SUFFIX!r} and use only "
            "lowercase letters, digits and underscores, starting with a letter, at most "
            f"{MAX_DATABASE_NAME_LENGTH} characters (got {name!r}). The test suite refuses any "
            "other name, so it can never reach a development or production database."
        )
    if development_database and name.lower() == development_database.lower():
        raise IsolationError(
            f"{TEST_DATABASE_URL_VAR} names the development database {name!r} "
            "(DATABASE_URL in .env). Use a separate database for tests."
        )
    return parsed


def _redis_db_number(url: str) -> int:
    """The test URL's database number: only a plain number in the path (or none, meaning 0)."""
    path = urlsplit(url).path.strip("/")
    if not path:
        return 0
    if not path.isdigit():
        raise IsolationError(f"{TEST_REDIS_URL_VAR} has an invalid database number {path!r}.")
    return int(path)


def validate_redis_url(url: str, *, development_redis_db: int) -> int:
    """Returns the Redis database number, or raises `IsolationError`."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError:
        raise IsolationError(f"{TEST_REDIS_URL_VAR} is not a valid Redis URL.") from None

    if parsed.scheme not in ALLOWED_REDIS_SCHEMES:
        raise IsolationError(
            f"{TEST_REDIS_URL_VAR} must be a redis:// or rediss:// URL (got {parsed.scheme!r})."
        )
    if not _is_loopback(host):
        raise IsolationError(
            f"{TEST_REDIS_URL_VAR} must point at this machine (localhost, 127.0.0.1 or ::1), "
            f"not {host!r}."
        )
    if parsed.query:
        raise IsolationError(f"{TEST_REDIS_URL_VAR} must not have query parameters.")
    number = _redis_db_number(url)
    try:
        client_number = redis_database_number(url)
    except IsolationError as exc:
        raise IsolationError(f"{TEST_REDIS_URL_VAR} is not usable: {exc}.") from None
    if client_number != number:  # never expected; refuse rather than guess which one is used
        raise IsolationError(f"{TEST_REDIS_URL_VAR} is ambiguous about its database number.")
    if number == development_redis_db:
        raise IsolationError(
            f"{TEST_REDIS_URL_VAR} uses Redis database {number}, the same number as REDIS_URL "
            "in .env. Use another number for tests, such as 15."
        )
    return number


def load_targets(
    environ: Mapping[str, str],
    *,
    test_env_file: Path = TEST_ENV_FILE,
    dev_env_file: Path = DEV_ENV_FILE,
) -> IsolationTargets:
    """Reads and validates the test targets. `dev_env_file` is read only for a configured one."""
    database_url, database_source = read_setting(TEST_DATABASE_URL_VAR, environ, test_env_file)
    redis_url, redis_source = read_setting(TEST_REDIS_URL_VAR, environ, test_env_file)

    if database_url is not None:
        validate_database_url(
            database_url, development_database=development_database_name(dev_env_file)
        )
    if redis_url is not None:
        validate_redis_url(redis_url, development_redis_db=development_redis_db(dev_env_file))

    return IsolationTargets(
        database_url=database_url or UNCONFIGURED_DATABASE_URL,
        redis_url=redis_url or UNCONFIGURED_REDIS_URL,
        database_configured=database_url is not None,
        redis_configured=redis_url is not None,
        database_source=database_source,
        redis_source=redis_source,
    )


def remove_case_variants(environ: MutableMapping[str, str]) -> list[str]:
    """Deletes every spelling of a guarded variable other than the upper-case one, and returns
    the names deleted (never their values).

    The application's settings match variable names case-insensitively, and when two spellings
    exist the later one wins: `database_url` set after `DATABASE_URL` would override the guard on
    a system with case-sensitive environment variables (Linux, macOS). Windows already treats the
    spellings as one variable, so there this finds nothing."""
    removed = [
        key for key in list(environ) if key.upper() in GUARDED_VARIABLES and key != key.upper()
    ]
    for key in removed:
        del environ[key]
    return removed


def settings_variable_names() -> frozenset[str]:
    """The upper-case environment-variable names of every application setting
    (`app.config.Settings` has no prefix or aliases: a field `debug` is the variable `DEBUG`)."""
    return frozenset(name.upper() for name in Settings.model_fields)


def live_llm_tests_allowed(environ: Mapping[str, str]) -> bool:
    """True only when `AEGIS_ALLOW_LIVE_LLM_TESTS` is exactly `1`."""
    return environ.get(LIVE_LLM_OPT_IN_VAR, "").strip() == "1"


def remove_inherited_settings(environ: MutableMapping[str, str]) -> list[str]:
    """Deletes every inherited variable named after an application setting, in any spelling, and
    returns the names deleted (never their values).

    A test process must not run with the developer's settings: an editor can copy all of `.env`
    into a terminal, and a shell can carry `DEBUG`, `ENVIRONMENT` or a Groq key. Only one exception
    is kept: the upper-case `GROQ_API_KEY`, when `AEGIS_ALLOW_LIVE_LLM_TESTS=1` asks for the
    billed live tests. Test-control variables (`TEST_*`, `RUN_*`, `AEGIS_*`) are not settings and
    are left alone."""
    names = settings_variable_names()
    keep = {"GROQ_API_KEY"} if live_llm_tests_allowed(environ) else set()
    removed = [key for key in list(environ) if key.upper() in names and key not in keep]
    for key in removed:
        del environ[key]
    return removed


def apply_targets(targets: IsolationTargets, environ: MutableMapping[str, str]) -> None:
    """Gives `environ` exactly the settings the tests may use: inherited application settings are
    removed (`remove_inherited_settings`), the database and Redis point at the validated test
    targets, `DEBUG` is `false` (so child processes inherit it too), and `GROQ_API_KEY` is empty
    unless `AEGIS_ALLOW_LIVE_LLM_TESTS=1` was set with it."""
    remove_inherited_settings(environ)
    environ["DATABASE_URL"] = targets.database_url
    environ["REDIS_URL"] = targets.redis_url
    environ["DEBUG"] = "false"
    if not live_llm_tests_allowed(environ):
        environ["GROQ_API_KEY"] = ""
    environ.setdefault("GROQ_API_KEY", "")


def disable_dotenv() -> None:
    """Stops `app.config.Settings` reading `.env` in this process, so settings come only from the
    code defaults, the environment prepared by `apply_targets` and what a test passes explicitly.
    Must run before any `Settings` exists (`ensure_application_not_configured_yet`)."""
    Settings.model_config["env_file"] = None


def ensure_application_not_configured_yet() -> None:
    """Refuses if the application's settings, database engine or Redis pool already exist in
    this process: they would still point wherever `.env` says."""
    for module in ("app.db.session", "app.db.redis"):
        if module in sys.modules:
            raise IsolationError(
                f"{module} was imported before the test isolation guard ran, so it may already "
                "be connected to the development services. configure_test_process() must run "
                "first (see backend/tests/conftest.py)."
            )
    config = sys.modules.get("app.config")
    if config is not None and config.get_settings.cache_info().currsize:
        raise IsolationError(
            "The application's settings were loaded before the test isolation guard ran. "
            "configure_test_process() must run first (see backend/tests/conftest.py)."
        )


_active: IsolationTargets | None = None


def configure_test_process() -> IsolationTargets:
    """Runs the guard for this process, once. Called from `backend/tests/__init__.py` (which every
    test module and conftest imports first, whatever pytest options are used) and again from
    `backend/tests/conftest.py`; the second call returns the first result."""
    global _active
    if _active is not None:
        return _active
    ensure_application_not_configured_yet()
    disable_dotenv()
    targets = load_targets(os.environ)
    apply_targets(targets, os.environ)
    _active = targets
    return targets


def active_targets() -> IsolationTargets:
    if _active is None:
        raise RuntimeError("configure_test_process() has not run in this process")
    return _active


# -- the live check, run once a connection to the test database works -------------------------


def wrong_database_message(*, expected: str, actual: str | None) -> str | None:
    """A reason to stop the whole run, or None. The server itself must report the expected
    `_test` database: a name check on the URL alone cannot see where a connection really went."""
    if actual == expected and (actual or "").endswith(REQUIRED_DATABASE_SUFFIX):
        return None
    return (
        f"Test isolation: the server reports database {actual!r}, but the tests were configured "
        f"for {expected!r}. Stopping before any test touches it."
    )


def migration_message(*, database: str, revision: str | None, head: str) -> str | None:
    """A reason to stop the run because the test database is not at the code's migration."""
    if revision == head:
        return None
    state = "has no migrations applied" if revision is None else f"is at revision {revision}"
    return (
        f"Test isolation: the test database {database!r} {state}, but the code expects revision "
        f"{head}. Migrate it with: {MIGRATE_COMMAND}"
    )


def alembic_head() -> str:
    """The newest migration revision in `backend/alembic/versions/` (read from the files; no
    database connection)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("backend/alembic/versions/ has no migrations")
    return head
