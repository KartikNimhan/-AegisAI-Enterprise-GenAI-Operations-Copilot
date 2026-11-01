"""Probe: was this pytest process isolated before the application loaded?

Runs as an ordinary unit test, and `test_isolation_entry_points.py` also runs it in fresh pytest
processes started in unusual ways (`--noconftest`, `--confcutdir`, other import modes) with a
fake development `DATABASE_URL`, a fake `DEBUG=true` and a dummy `GROQ_API_KEY` in their
environment. It never connects anywhere, and its assertion compares only booleans, so a failure
cannot print a URL, a key or a password.
"""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.db import session as session_module
from tests import isolation


def test_the_isolation_guard_ran_before_the_application_loaded() -> None:
    targets = isolation._active  # set only by configure_test_process()
    settings = get_settings()
    guard_ran = targets is not None
    settings_name = make_url(settings.database_url).database or ""
    engine_name = session_module.engine.url.database or ""
    settings_follow_guard = targets is not None and settings.database_url == targets.database_url
    redis_follows_guard = targets is not None and settings.redis_url == targets.redis_url
    names_are_test_names = settings_name.endswith("_test") and engine_name.endswith("_test")
    isolated = guard_ran and settings_follow_guard and redis_follows_guard and names_are_test_names

    assert isolated, "the test-isolation guard did not run before the application loaded"


def test_development_settings_cannot_reach_this_process() -> None:
    settings = get_settings()
    dotenv_disabled = Settings.model_config.get("env_file") is None
    debug_off = settings.debug is False and settings.sql_echo is False
    debug_variable_false = os.environ.get("DEBUG") == "false"
    opted_in = isolation.live_llm_tests_allowed(os.environ)
    no_groq_key = opted_in or (
        os.environ.get("GROQ_API_KEY") == "" and settings.has_groq_api_key is False
    )
    sanitized = dotenv_disabled and debug_off and debug_variable_false and no_groq_key

    assert sanitized, "development settings reached the test process"
