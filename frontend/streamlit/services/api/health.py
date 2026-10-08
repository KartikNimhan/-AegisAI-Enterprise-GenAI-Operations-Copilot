"""The Health API module — wraps the existing, unversioned
`/health`/`/health/ready` probes (Milestone 0). `/health/ready`'s 503
"degraded" response is itself meaningful data to render, not a failure —
`ok_status_codes` accepts both.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import request_json


@dataclass(frozen=True)
class ReadinessStatus:
    status: str
    database: str
    redis: str


def get_readiness() -> ReadinessStatus:
    payload = request_json("GET", "/health/ready", ok_status_codes=(200, 503))
    return ReadinessStatus(
        status=payload["status"], database=payload["database"], redis=payload["redis"]
    )
