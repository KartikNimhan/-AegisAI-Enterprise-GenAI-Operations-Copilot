"""Which data the stdio MCP server may see. It fails closed.

`scripts/mcp_stdio_server.py` has no signed-in caller, and an unrestricted scope reads every
document of every organization. Starting it must therefore be a deliberate choice, never a default:

- `MCP_STDIO_USER_ID` + `MCP_STDIO_ORGANIZATION_ID` (UUIDs): serve exactly what that user may read,
  through the same ownership rules as the API. The preferred way to run it.
- `MCP_STDIO_ALLOW_UNRESTRICTED=true`: serve everything, across organizations. For an operator on
  the host that holds the database, who already has that access.
- Neither (or both, or a partial or malformed identity): refuse to start.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from app.auth.scope import AccessScope

USER_ID_VAR = "MCP_STDIO_USER_ID"
ORGANIZATION_ID_VAR = "MCP_STDIO_ORGANIZATION_ID"
ALLOW_UNRESTRICTED_VAR = "MCP_STDIO_ALLOW_UNRESTRICTED"


class StdioScopeError(Exception):
    """The environment does not say, unambiguously, whose data the server may expose."""


def resolve_stdio_scope(environ: Mapping[str, str]) -> AccessScope:
    user = environ.get(USER_ID_VAR, "").strip()
    organization = environ.get(ORGANIZATION_ID_VAR, "").strip()
    unrestricted = environ.get(ALLOW_UNRESTRICTED_VAR, "").strip().lower() == "true"

    if (user or organization) and unrestricted:
        raise StdioScopeError(
            f"Set either {USER_ID_VAR}/{ORGANIZATION_ID_VAR} or {ALLOW_UNRESTRICTED_VAR}=true, "
            "not both."
        )
    if user or organization:
        try:
            return AccessScope.for_user(
                user_id=uuid.UUID(user), organization_id=uuid.UUID(organization)
            )
        except ValueError:
            raise StdioScopeError(
                f"{USER_ID_VAR} and {ORGANIZATION_ID_VAR} must both be set to valid UUIDs."
            ) from None
    if unrestricted:
        return AccessScope.unrestricted_for_operators()
    raise StdioScopeError(
        "Refusing to start: this server would expose documents without a caller. Set "
        f"{USER_ID_VAR} and {ORGANIZATION_ID_VAR} to serve one user's data, or "
        f"{ALLOW_UNRESTRICTED_VAR}=true to knowingly serve every organization's data."
    )
