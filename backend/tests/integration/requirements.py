"""What an integration test does when a service it needs is not there.

Locally, a missing Postgres or Redis means "skip": these tests are meant to be run when the
services are up, and a developer without them should still get a clean unit run. In CI the
services are part of the job, so a missing one is a broken job, not a reason to skip: if the
Postgres container failed to start, every isolation, repository and migration test used to skip
and the run still showed green. CI sets `AEGIS_REQUIRE_SERVICES=1`, which turns those skips into
failures.

Only *infrastructure* gaps go through here. The opt-in gates for live providers (`GROQ_API_KEY`,
`RUN_*_INTEGRATION`) stay ordinary skips, because CI deliberately does not run them.
"""

from __future__ import annotations

import os
from typing import NoReturn

import pytest

REQUIRE_SERVICES_VAR = "AEGIS_REQUIRE_SERVICES"


def services_required() -> bool:
    return os.environ.get(REQUIRE_SERVICES_VAR, "").strip() == "1"


def service_unavailable(reason: str) -> NoReturn:
    """Skips the test, or fails it when the run requires its services (see the module docstring)."""
    if services_required():
        pytest.fail(
            f"{reason}. {REQUIRE_SERVICES_VAR}=1 says this run must have its services, "
            "so this is a failure, not a skip.",
            pytrace=False,
        )
    pytest.skip(reason)
