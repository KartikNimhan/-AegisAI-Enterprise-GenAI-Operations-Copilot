"""Docker/Kubernetes health check for the Streamlit frontend container.

Hits Streamlit's own real, built-in health endpoint,
`/_stcore/health` — confirmed present in the installed `streamlit`
package (`streamlit/web/server/starlette/starlette_routes.py`), not
invented for this milestone. Uses only the standard library — no
`curl`/`wget` installed in the runtime image.
"""

from __future__ import annotations

import os
import sys
import urllib.request

PORT = os.environ.get("PORT", "8501")
URL = f"http://127.0.0.1:{PORT}/_stcore/health"


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
