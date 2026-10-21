"""Assigns pre-ownership conversations and documents to a named user (operator command).

Conversations and documents created before ownership existed have no owner, so no
signed-in user can see them (by design: unowned data is invisible, not exposed).
Run this once, after provisioning the user who should receive them
(`scripts/provision_identity.py`) and after migration 0006 but BEFORE migration 0007
(which makes the owner required):

    docker compose run --rm migrate alembic upgrade 0006      # step 1: add the columns
    uv run python scripts/assign_legacy_data.py \
        --email you@example.com --organization "Acme" --dry-run
    uv run python scripts/assign_legacy_data.py \
        --email you@example.com --organization "Acme" --yes
    docker compose run --rm migrate alembic upgrade head      # step 2: require an owner

Safe by construction (see `app/auth/legacy_assignment.py`): it never guesses. You must name BOTH
the user (`--email`) and the organization (`--organization`); both must already exist, be active,
and agree (the user must belong to that organization), or nothing is changed. It only fills in a
MISSING owner, so a row that already belongs to someone is never touched; nothing is deleted.
Documents stay private to the new owner.

`--expect-conversations N` / `--expect-documents N` make it abort, changing nothing, if
the number of unowned rows differs from what you expect.

It writes to the database named by the application settings (`DATABASE_URL`). It prints the
target (host, port, database name; never the password) and, unless `--dry-run` is given,
requires `--yes` to commit. `--dry-run` does everything inside a transaction and rolls it
back. It is idempotent: a second run finds nothing to assign.

Run from anywhere: the backend package is located relative to this file.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign conversations and documents that have no owner to a user.",
    )
    parser.add_argument("--email", required=True, help="the email of the (provisioned) new owner")
    parser.add_argument(
        "--organization", required=True, help="the name of that user's organization (must match)"
    )
    parser.add_argument("--expect-conversations", type=int, default=None, metavar="N")
    parser.add_argument("--expect-documents", type=int, default=None, metavar="N")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and report; change nothing"
    )
    parser.add_argument("--yes", action="store_true", help="confirm writing to the database")
    return parser.parse_args(argv)


def database_target(database_url: str) -> str:
    """host:port/name of the database, never the credentials."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    return f"{url.host or 'localhost'}:{url.port or 'default'}/{url.database}"


async def run(
    args: argparse.Namespace,
    *,
    target: str,
    session_factory: Callable[[], Any],
    store_factory: Callable[[Any], Any],
) -> int:
    """The command's logic with its collaborators injected (see the unit tests).
    Returns the process exit code."""
    from app.auth.legacy_assignment import AssignmentError, assign_legacy_data

    if not args.dry_run and not args.yes:
        print(
            f"error: this would write to the database at {target}. "
            "Re-run with --dry-run to preview, or --yes to commit.",
            file=sys.stderr,
        )
        return 2

    print(f"Database: {target}")
    async with session_factory() as session:
        try:
            result = await assign_legacy_data(
                store_factory(session),
                email=args.email,
                organization_name=args.organization,
                expect_conversations=args.expect_conversations,
                expect_documents=args.expect_documents,
            )
        except AssignmentError as exc:
            await session.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    prefix = "[dry run, nothing written] " if args.dry_run else ""
    if not result.changed:
        print(f"{prefix}No unowned conversations or documents: nothing to assign.")
    else:
        verb = "Would assign" if args.dry_run else "Assigned"
        print(
            f"{prefix}{verb} {result.conversations} conversation(s) and "
            f"{result.documents} document(s) to {args.email!r} in {args.organization!r}."
        )
    print(f"user_id={result.user_id} organization_id={result.organization_id}")
    return 0


class _Store:
    """The identity lookups and the ownership queries behind one object."""

    def __init__(self, session: Any) -> None:
        from app.db.repositories.identity_repository import IdentityRepository
        from app.db.repositories.legacy_ownership_repository import LegacyOwnershipRepository

        identities = IdentityRepository(session)
        legacy = LegacyOwnershipRepository(session)
        self.get_user_by_email = identities.get_user_by_email
        self.get_organization_by_name = identities.get_organization_by_name
        self.count_unowned = legacy.count_unowned
        self.assign_unowned = legacy.assign_unowned


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal

    settings = get_settings()
    return asyncio.run(
        run(
            args,
            target=database_target(settings.database_url),
            session_factory=AsyncSessionLocal,
            store_factory=_Store,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
