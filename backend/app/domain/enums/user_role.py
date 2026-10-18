"""Roles an internal user can hold.

Deliberately tiny: `member` is an ordinary employee, `admin` is the small,
restricted administrator role. Role is always read from the database row —
never from a token claim — see `app.auth.service`.
"""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    MEMBER = "member"
    ADMIN = "admin"
