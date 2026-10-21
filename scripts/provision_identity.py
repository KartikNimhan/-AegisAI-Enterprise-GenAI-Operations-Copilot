"""Links an identity-provider account to an internal user (operator command).

AegisAI has no self-service sign-up: a person can use the API only after an
operator links their identity-provider account to an internal user and
organization. This command does that: it creates the organization and user if
they do not exist and links `(issuer, subject)` to the user. Run it once per
person, e.g. for the first administrator.

`--subject` is the token's `sub` claim (with Keycloak, the user's ID shown in
the admin console) and `--issuer` must equal the token's `iss` claim EXACTLY; it
defaults to `AUTH_ISSUER` from the application settings.

Safe by construction (see `app/auth/provisioning.py`): it only adds rows, is
idempotent, and refuses (rather than silently changing) anything that already
exists differently: a disabled user or organization, a different role, a
different organization, or an identity linked to someone else.

It writes to the database named by the application settings (`DATABASE_URL`). It
prints the target (host, port, database name; never the password) and, unless
`--dry-run` is given, requires `--yes` to commit. `--dry-run` does everything
inside a transaction and rolls it back.

Usage:
    uv run python scripts/provision_identity.py --organization "Acme" \\
        --email admin@example.com --subject <sub claim> --role admin --dry-run
    uv run python scripts/provision_identity.py --organization "Acme" \\
        --email admin@example.com --subject <sub claim> --role admin --yes

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
        description="Link an identity-provider account to an internal user.",
    )
    parser.add_argument("--organization", required=True, help="organization name (created if new)")
    parser.add_argument("--email", required=True, help="the user's email address")
    parser.add_argument("--subject", required=True, help="the token's `sub` claim")
    parser.add_argument(
        "--issuer",
        default=None,
        help="the token's `iss` claim exactly (default: AUTH_ISSUER from the settings)",
    )
    parser.add_argument("--role", choices=("member", "admin"), default="member")
    parser.add_argument("--display-name", default=None)
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
    issuer_default: str | None,
    target: str,
    session_factory: Callable[[], Any],
    store_factory: Callable[[Any], Any],
) -> int:
    """The command's logic with its collaborators injected (see the unit tests).
    Returns the process exit code."""
    from app.auth.provisioning import ProvisioningError, provision_identity
    from app.domain.enums.user_role import UserRole

    issuer = args.issuer or issuer_default
    if not issuer:
        print("error: --issuer is required (AUTH_ISSUER is not set).", file=sys.stderr)
        return 2
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
            result = await provision_identity(
                store_factory(session),
                organization_name=args.organization,
                email=args.email,
                issuer=issuer,
                subject=args.subject,
                role=UserRole(args.role),
                display_name=args.display_name,
            )
        except ProvisioningError as exc:
            await session.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1

        if args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    prefix = "[dry run, nothing written] " if args.dry_run else ""
    if not result.changed:
        print(f"{prefix}Already provisioned: nothing to change.")
    else:
        parts = []
        if result.organization_created:
            parts.append(f"organization {args.organization!r}")
        if result.user_created:
            parts.append(f"user {args.email!r} ({args.role})")
        if result.identity_linked:
            parts.append("identity link")
        print(f"{prefix}Would create: " if args.dry_run else "Created: ", end="")
        print(", ".join(parts) + ".")
    print(f"user_id={result.user_id} organization_id={result.organization_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    from app.config import get_settings
    from app.db.repositories.identity_repository import IdentityRepository
    from app.db.session import AsyncSessionLocal

    settings = get_settings()
    return asyncio.run(
        run(
            args,
            issuer_default=settings.auth_issuer,
            target=database_target(settings.database_url),
            session_factory=AsyncSessionLocal,
            store_factory=IdentityRepository,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
