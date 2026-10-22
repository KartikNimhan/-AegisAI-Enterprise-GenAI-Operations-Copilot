# 13. Data Isolation: Ownership, Organizations and Roles

> **Milestone numbering.** Milestone numbers in this document use the project's earlier
> working numbering, not the [Official Project Roadmap](../../../README.md#official-project-roadmap).
> They record what was built under that numbering and are not redefined by the roadmap.

## Status

Accepted — 2026-10-21. Implemented and verified offline; the database-backed tests described
below exist but had not been run when this was written.

## Context

Authentication (Milestone 12, Phase 1a) established *who* is calling: every `/api/v1` route needs
a verified token that maps to an active user in an active organization. It did not decide *whose
data* that user may reach. No business table had an owner, no route passed the caller's identity
to a repository, and so any signed-in user could read, search, continue and delete everyone's
documents and conversations, across organizations. The audit that found this also showed that
the only role check (`require_admin`) was defined but used nowhere.

## Decision

**Ownership.** `conversations` and `documents` each carry `owner_user_id` and `organization_id`.
Messages, chunks and embeddings have no owner of their own; they are reached only through their
conversation or document, and every query joins to that parent.

**Rules** (implemented once, in `app.auth.scope.AccessScope`):

| Data | Who may read | Who may delete / re-share |
|---|---|---|
| Conversation, its messages | its owner only (administrators included: no special access) | its owner |
| Document, its chunks and embeddings | its owner; and, when `visibility = 'organization'`, members of the owner's organization | its owner, or an administrator of the owner's organization |
| Operations summary (counts by status) | a member: counts over what they may read. An administrator: counts over the whole organization (aggregate numbers only) | n/a |

A document is `private` by default; sharing is an explicit, reversible act
(`PATCH /api/v1/documents/{id}/visibility`). An administrator can remove a member's private
document without being able to read it. Nothing ever crosses organizations. Embedding a document
needs the same management rights as deleting it, because it spends compute.

**Not found, not forbidden.** A resource outside the caller's scope is reported exactly like one
that does not exist (404), so a guessed identifier reveals nothing. This includes the streaming
endpoints (their setup is now completed before the response starts, so an unknown conversation
is a 404 there too rather than a committed 200).

**Enforcement is structural.** Repositories take an `AccessScope` as a required constructor
argument and apply it in SQL, before any `LIMIT`; the FastAPI dependency that builds a scope
requires the authenticated principal. Tools, the MCP adapters and the A2A specialists are built
from the same scoped repositories, so enforcement sits below the language model and cannot be
widened by a prompt. The only unrestricted scope is for operator tooling (`scripts/`), and a test
asserts that nothing under `app/` uses it.

**Duplicate detection is per owner.** Uploading bytes the caller already uploaded is a duplicate;
bytes only someone else holds are a new document, so an upload cannot reveal that another user or
organization has the same file. Because two owners may therefore hold identical content, chunk
ids now derive from the **document id**, not the content checksum (which would collide on the
chunk primary key).

**Roles.** `member` and `admin` as before, always read from the database row. `/system/status`
(infrastructure facts) is administrator-only. No other administrator capability exists yet; there
is still no user-management API.

**Schema** (migrations 0006 and 0007). 0006 adds the columns as nullable, a unique
`(users.id, users.organization_id)` so that a composite foreign key can make the database itself
guarantee an owner belongs to the row's organization, check constraints, indexes, and
`documents.visibility`. Foreign keys are `ON DELETE RESTRICT`: a user who owns data cannot be
deleted out from under it. 0007 makes the columns `NOT NULL`, and refuses to run while any row is
unowned. In between, an unowned row matches no caller's scope and is invisible rather than exposed.
Existing data is assigned by `scripts/assign_legacy_data.py`, a command (not part of a migration)
because choosing the owner is a human decision. It never guesses: the operator must name both the
user and the organization, both must exist, be active and agree, or nothing changes. See the README, "Authentication
setup", for the exact upgrade sequence.

## Consequences

- Existing databases need the two-step upgrade; until the backfill, pre-existing conversations and
  documents are invisible to everyone. Fresh installs are unaffected.
- A downgrade past 0006 discards ownership assignments (and the isolation they provide) but
  deletes no conversation, message or document.
- The evaluation harness seeds its corpus under a throwaway organization and user, so it measures
  retrieval through the real scoped code path.
- `scripts/mcp_stdio_server.py` is an operator tool with no signed-in caller. It no longer starts
  unrestricted by default: the operator must name one user and organization, or set
  `MCP_STDIO_ALLOW_UNRESTRICTED=true` to knowingly serve every document. It is not reachable
  through the API.
- An administrator can delete, but not read, a member's private document, which is deliberate.

## Alternatives considered

- **Organization-wide access to everything:** rejected; membership alone should not expose a
  colleague's private conversations or documents.
- **Letting administrators read members' data:** rejected for now; deletion and re-sharing cover
  the operational need without that privilege.
- **PostgreSQL row-level security:** deferred. It would be a sound second layer under the
  application-level scoping adopted here, but should be added only once this layer is verified
  against a real database.
- **A database `UNIQUE (owner_user_id, checksum)`:** not adopted; duplicate detection stays a
  service-level decision (ADR 005), with a non-unique composite index.

## Verification

Offline (run): the scope rules executed as real SQL over a population of two organizations
including unowned rows; every repository method asserted to bind the caller's identifiers (and
mutation-checked: disabling a predicate makes these fail); structural guards (repositories require
a scope, no unrestricted scope under `app/`, every data route asks for the scope); the migrations'
rendered SQL (additive only; names match the models; 0007 refuses while rows are unowned); the
backfill command; and the service-level delete/re-share/duplicate behavior.

Database-backed (written, **not yet run**): `tests/integration/test_data_isolation.py` drives the
HTTP app as five users in two organizations across every path in this document, including guessed
ids, continuing someone's conversation, retrieval ranking with other owners' better matches, and the
agent tool; `tests/integration/test_ownership_migration.py` upgrades a throwaway database holding
pre-ownership data through 0006, the refusal, the backfill and 0007, and back down.
