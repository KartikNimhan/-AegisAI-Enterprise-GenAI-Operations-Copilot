"""Docker/Kubernetes health check for the backend container.

Hits the real `/health` liveness endpoint (`app.api.v1.health`) using only
the standard library — no `curl`/`wget` installed in the runtime image,
keeping it minimal. Deliberately checks `/health`, not `/health/ready`:
a container HEALTHCHECK / Kubernetes liveness probe should answer "is this
process still alive and serving," not "are all its external dependencies
currently reachable" — the same distinction
docs/architecture/decisions/012-deployment-architecture.md makes between
Docker's `HEALTHCHECK` and Kubernetes' separate liveness/readiness probes.
"""

from __future__ import annotations

import os
import sys
import urllib.request

PORT = os.environ.get("PORT", "8000")
URL = f"http://127.0.0.1:{PORT}/health"


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
