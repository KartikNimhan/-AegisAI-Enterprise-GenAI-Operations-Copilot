"""Repository abstractions over persisted entities.

Every SQLAlchemy-specific detail (sessions, `select()`, eager-loading
strategy) lives here. Services depend on these repositories, never on
`AsyncSession`/queries directly.
"""
