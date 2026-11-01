"""The backend test package.

Under pytest, importing this package runs the test-isolation guard (`isolation.py`) before
anything else. Every test module and every conftest under `backend/tests/` belongs to this
package, and pytest imports a package before its modules in every import mode, so the guard runs
first even with `--noconftest` or a `--confcutdir` that skips `backend/tests/conftest.py`
(`tests/unit/test_isolation_entry_points.py` proves this by running pytest each of those ways).

Outside pytest (for example `scripts/test_db.py`, which imports `tests.isolation` for its rules)
nothing runs here.
"""

import sys

if "_pytest" in sys.modules:
    from .isolation import configure_test_process

    configure_test_process()
