"""Audit events for security-sensitive actions.

One structured log line per sensitive action (a document uploaded, shared, embedded or deleted;
a conversation deleted; a request refused by a rate limit), attributed to the authenticated user
and organization and to the resource's id. The request id is added by the logging configuration
(see `app.core.logging`), so an audit line can be joined to the access log of the same request.

What is deliberately NOT here: any content (document text, messages, file names, titles), any
token, secret or e-mail address. `record` only accepts a resource *type* and *id* plus a few
primitive, non-sensitive facts, and refuses details that look like content or credentials, so a
careless call site cannot start leaking data into the logs.

An attempt on a resource the caller may not touch is recorded as `not_found`, the same word the
API uses for a resource that does not exist: the audit trail must not distinguish the two either,
but repeated `not_found` attempts by one actor are still visible as a pattern.

These are log lines, not an immutable audit store: shipping them to tamper-evident storage is a
deployment decision (see docs/operations/production-readiness.md).
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog

from app.auth.principal import Principal

logger = structlog.get_logger("aegisai.audit")

Outcome = Literal["success", "not_found", "limited"]

_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "content",
        "text",
        "message",
        "title",
        "filename",
        "file_name",
        "email",
        "token",
        "authorization",
        "password",
        "secret",
        "key",
        "claims",
    }
)


def record(
    action: str,
    *,
    actor: Principal,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    outcome: Outcome = "success",
    **details: str | int | bool | None,
) -> None:
    forbidden = _FORBIDDEN_DETAIL_KEYS & {key.lower() for key in details}
    if forbidden:
        raise ValueError(
            f"audit details must not carry content or credentials: {sorted(forbidden)}"
        )
    log = logger.warning if outcome == "limited" else logger.info
    log(
        "audit",
        audit_action=action,
        audit_outcome=outcome,
        actor_user_id=str(actor.user_id),
        actor_organization_id=str(actor.organization_id),
        actor_role=actor.role.value,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        **details,
    )
