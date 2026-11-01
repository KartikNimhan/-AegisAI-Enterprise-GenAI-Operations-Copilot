"""No pytest entry point reaches the development database: the guard runs however pytest starts.

The guard runs when pytest first imports the `tests` package (`backend/tests/__init__.py`).
These tests prove that, rather than assume it:

- **Fresh pytest processes.** `test_isolation_probe.py` is run in new pytest processes started
  every way that skips `backend/tests/conftest.py` or changes how modules are imported:
  `--noconftest` (also through `PYTEST_ADDOPTS`), `--confcutdir`, each `--import-mode`, another
  rootdir, an empty config file, and another working directory. Each child gets a fake
  development `DATABASE_URL` naming `aegis` on port 1 (where nothing listens) instead of the
  guarded value, so a child in which the guard did not run would fail the probe; nothing
  connects either way. A control run shows the same environment really does select `aegis`
  when the guard is not involved.
- **The precondition.** Every folder holding tests is a package below `backend/tests`, so its
  modules are always imported through the `tests` package; and no test file elsewhere imports
  the application.
- **The fixtures fail closed.** The integration and evaluation database fixtures go through
  `tests/live_database.py`, which refuses to run if the guard has not, and stops the run when
  the server is not the configured `_test` database.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import live_database
from tests.isolation import (
    DATABASE_NAME_PATTERN,
    MAX_DATABASE_NAME_LENGTH,
    REPO_ROOT,
    UNCONFIGURED_DATABASE_URL,
    IsolationTargets,
)

TESTS_DIR = REPO_ROOT / "backend" / "tests"
PROBE = "backend/tests/unit/test_isolation_probe.py"
FAKE_DEV_DATABASE_URL = "postgresql+asyncpg://dev_user:not-a-password@127.0.0.1:1/aegis"
FAKE_DEV_REDIS_URL = "redis://127.0.0.1:1/0"
# A dummy, never a real key: the children only check that it does not survive the guard.
FAKE_INHERITED_GROQ_KEY = "dummy-inherited-key-not-real"
_STRIPPED = {
    "DATABASE_URL",
    "REDIS_URL",
    "GROQ_API_KEY",
    "DEBUG",
    "TEST_DATABASE_URL",
    "TEST_REDIS_URL",
    "AEGIS_ALLOW_LIVE_LLM_TESTS",  # never opted in here: no child may run a billed test
}


def _child_environment(**extra: str) -> dict[str, str]:
    """This environment without the guarded values and without pytest's own variables, plus what
    an editor that copied `.env` into the terminal would leave behind: a development
    `DATABASE_URL`, `DEBUG=true` and a Groq key (all fake)."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _STRIPPED and not key.upper().startswith("PYTEST_")
    }
    env.update(
        DATABASE_URL=FAKE_DEV_DATABASE_URL,
        REDIS_URL=FAKE_DEV_REDIS_URL,
        DEBUG="true",
        GROQ_API_KEY=FAKE_INHERITED_GROQ_KEY,
        PYTHONDONTWRITEBYTECODE="1",
        **extra,
    )
    return env


def _run_pytest(args: list[str], *, cwd: Path = REPO_ROOT, **env: str) -> tuple[int, str]:
    completed = subprocess.run(  # noqa: S603 - this interpreter, pytest, a file in this repo
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=cwd,
        env=_child_environment(**env),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    tail = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-15:])
    return completed.returncode, tail


# -- fresh pytest processes ------------------------------------------------------------------


def _invocations(empty_config: Path) -> dict[str, tuple[list[str], Path, dict[str, str]]]:
    """`name -> (pytest arguments, working directory, extra environment)`."""
    here = REPO_ROOT
    return {
        "plain": ([PROBE], here, {}),
        "noconftest": (["--noconftest", PROBE], here, {}),
        "noconftest-via-PYTEST_ADDOPTS": ([PROBE], here, {"PYTEST_ADDOPTS": "--noconftest"}),
        "confcutdir-unit": (["--confcutdir", "backend/tests/unit", PROBE], here, {}),
        "confcutdir-integration": (["--confcutdir", "backend/tests/integration", PROBE], here, {}),
        "confcutdir-evaluation": (["--confcutdir", "backend/tests/evaluation", PROBE], here, {}),
        "import-mode-importlib": (["--import-mode=importlib", PROBE], here, {}),
        "import-mode-append": (["--import-mode=append", PROBE], here, {}),
        "noconftest-importlib": (["--noconftest", "--import-mode=importlib", PROBE], here, {}),
        "noconftest-append": (["--noconftest", "--import-mode=append", PROBE], here, {}),
        "rootdir-backend-noconftest": (["--rootdir", "backend", "--noconftest", PROBE], here, {}),
        "cwd-backend-noconftest": (
            ["--noconftest", "tests/unit/test_isolation_probe.py"],
            REPO_ROOT / "backend",
            {},
        ),
        "empty-config-noconftest": (
            ["-c", str(empty_config), "--noconftest", str(REPO_ROOT / PROBE)],
            here,
            {},
        ),
    }


INVOCATION_NAMES = list(_invocations(Path("unused")))


@pytest.fixture(scope="module")
def child_results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[int, str]]:
    """Runs every invocation at once (each is a separate pytest process)."""
    empty_config = tmp_path_factory.mktemp("empty-config") / "pytest.ini"
    empty_config.write_text("[pytest]\n", encoding="utf-8")
    invocations = _invocations(empty_config)
    with ThreadPoolExecutor(max_workers=min(8, len(invocations))) as pool:
        futures = {
            name: pool.submit(_run_pytest, args, cwd=cwd, **env)
            for name, (args, cwd, env) in invocations.items()
        }
        return {name: future.result() for name, future in futures.items()}


@pytest.mark.parametrize("name", INVOCATION_NAMES)
def test_the_guard_runs_however_pytest_is_started(
    child_results: dict[str, tuple[int, str]], name: str
) -> None:
    code, tail = child_results[name]

    # Both probes: the database guard, and the sanitized settings (no .env file, DEBUG off, no
    # SQL logging, no Groq key) despite the fake inherited DEBUG=true and key.
    assert code == 0 and "2 passed" in tail, tail


def test_control_without_the_guard_the_same_environment_selects_the_development_settings() -> None:
    # Proves the children above really had `aegis`, debug and a Groq key to fall back to.
    # Prints three booleans only.
    code = (
        "import sys; sys.path.insert(0, 'backend'); "
        "from app.config import Settings; "
        "s = Settings(_env_file=None); "
        "print(s.database_url.rsplit('/', 1)[1] == 'aegis', s.debug, s.has_groq_api_key)"
    )
    completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed snippet
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_child_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "True True True"


# -- the precondition --------------------------------------------------------------------------


def test_every_folder_with_tests_is_a_package_below_backend_tests() -> None:
    missing = []
    for path in TESTS_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if not (path.name.startswith("test_") or path.name == "conftest.py"):
            continue
        folder = path.parent
        while folder != TESTS_DIR.parent:
            if not (folder / "__init__.py").is_file():
                missing.append(folder.relative_to(REPO_ROOT).as_posix())
            folder = folder.parent

    assert sorted(set(missing)) == []


def _test_files_outside_backend_tests() -> Iterator[Path]:
    skip = {".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build"}
    for folder, subfolders, files in os.walk(REPO_ROOT):
        subfolders[:] = [name for name in subfolders if name not in skip]
        here = Path(folder)
        if here == TESTS_DIR or TESTS_DIR in here.parents:
            subfolders[:] = []
            continue
        for name in files:
            if name.endswith(".py") and (
                name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            ):
                yield here / name


def test_no_test_file_outside_backend_tests_imports_the_application() -> None:
    offenders = []
    for path in _test_files_outside_backend_tests():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name == "app" or name.startswith("app.") for name in names):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert sorted(set(offenders)) == []


def test_pytest_collects_only_from_the_tests_package() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["backend/tests"]


@pytest.mark.parametrize("module", ["test_identity_migration.py", "test_ownership_migration.py"])
def test_the_migration_round_trips_name_their_throwaway_databases_like_test_databases(
    module: str,
) -> None:
    # Read from the source (these opt-in tests are not run here): `name = f"...{hex}..._test"`.
    tree = ast.parse((TESTS_DIR / "integration" / module).read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and [getattr(t, "id", None) for t in node.targets] == ["name"]
            and isinstance(node.value, ast.JoinedStr)
        ):
            names.append(
                "".join(
                    str(part.value) if isinstance(part, ast.Constant) else "0123456789ab"
                    for part in node.value.values
                )
            )

    assert len(names) == 1
    assert len(names[0]) <= MAX_DATABASE_NAME_LENGTH
    assert DATABASE_NAME_PATTERN.fullmatch(names[0]), names[0]


def test_the_package_runs_the_guard_under_pytest() -> None:
    tree = ast.parse((TESTS_DIR / "__init__.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "configure_test_process"
    ]

    assert len(calls) == 1


# -- the database fixtures fail closed ---------------------------------------------------------


@pytest.mark.parametrize(
    "conftest", ["integration/conftest.py", "evaluation/conftest.py"], ids=["integration", "eval"]
)
def test_both_database_fixtures_use_the_shared_live_check(conftest: str) -> None:
    tree = ast.parse((TESTS_DIR / conftest).read_text(encoding="utf-8"))
    fixture = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "db_session"
    )
    first = fixture.body[0]

    # The very first statement, before the fixture opens any session.
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Await)
    call = first.value.value
    assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "require_test_database"


def _targets(*, configured: bool) -> IsolationTargets:
    return IsolationTargets(
        database_url=(
            "postgresql+asyncpg://aegis:pw@localhost:5432/aegis_test"
            if configured
            else UNCONFIGURED_DATABASE_URL
        ),
        redis_url="redis://127.0.0.1:1/15",
        database_configured=configured,
        redis_configured=False,
        database_source="environment" if configured else "not configured",
        redis_source="not configured",
    )


class _FakeSession:
    """Answers the three live-check queries from a script; never connects."""

    def __init__(self, answers: dict[str, Any], calls: list[str]) -> None:
        self._answers = answers
        self._calls = calls

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def scalar(self, statement: Any) -> Any:
        sql = str(statement)
        self._calls.append(sql)
        for fragment, answer in self._answers.items():
            if fragment in sql:
                return answer
        raise AssertionError(f"unexpected query: {sql}")


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Any:
    live_database.reset_for_tests()
    monkeypatch.delenv("AEGIS_REQUIRE_SERVICES", raising=False)
    calls: list[str] = []

    def configure(*, configured: bool, reachable: bool = True, **answers: Any) -> None:
        monkeypatch.setattr(
            live_database, "active_targets", lambda: _targets(configured=configured)
        )

        async def check_database(timeout: float = 2.0) -> bool:
            return reachable

        monkeypatch.setattr(live_database, "check_database", check_database)
        monkeypatch.setattr(live_database, "alembic_head", lambda: "0008")
        scripted = {
            "current_database": answers.get("current", "aegis_test"),
            "to_regclass": answers.get("has_versions", True),
            "alembic_version": answers.get("revision", "0008"),
        }
        monkeypatch.setattr(
            live_database, "AsyncSessionLocal", lambda: _FakeSession(scripted, calls)
        )

    yield SimpleNamespace(configure=configure, calls=calls)
    live_database.reset_for_tests()


async def test_a_fixture_cannot_run_when_the_guard_has_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_configured() -> IsolationTargets:
        raise RuntimeError("configure_test_process() has not run in this process")

    live_database.reset_for_tests()
    monkeypatch.setattr(live_database, "active_targets", not_configured)

    with pytest.raises(RuntimeError, match="has not run"):
        await live_database.require_test_database()


async def test_no_configured_test_database_means_a_skip(live: Any) -> None:
    live.configure(configured=False)

    with pytest.raises(pytest.skip.Exception, match="No test database is configured"):
        await live_database.require_test_database()
    assert live.calls == []


async def test_an_unreachable_test_database_means_a_skip(live: Any) -> None:
    live.configure(configured=True, reachable=False)

    with pytest.raises(pytest.skip.Exception, match="not reachable"):
        await live_database.require_test_database()
    assert live.calls == []


@pytest.mark.parametrize("current", ["aegis", "aegis_test_other", None])
async def test_the_run_stops_when_the_server_reports_another_database(
    live: Any, current: str | None
) -> None:
    live.configure(configured=True, current=current)

    with pytest.raises(pytest.exit.Exception, match="Stopping before any test touches it"):
        await live_database.require_test_database()


@pytest.mark.parametrize(
    ("answers", "expected"),
    [({"has_versions": False}, "no migrations applied"), ({"revision": "0007"}, "revision 0007")],
)
async def test_the_run_stops_when_the_test_database_is_not_migrated(
    live: Any, answers: dict[str, Any], expected: str
) -> None:
    live.configure(configured=True, **answers)

    with pytest.raises(pytest.exit.Exception, match=expected):
        await live_database.require_test_database()


async def test_a_verified_test_database_is_checked_once(live: Any) -> None:
    live.configure(configured=True)

    await live_database.require_test_database()
    queries = len(live.calls)
    await live_database.require_test_database()

    assert queries == 3
    assert len(live.calls) == queries
