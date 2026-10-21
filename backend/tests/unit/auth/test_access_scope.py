"""The ownership rules, executed as real SQL.

`AccessScope` builds the WHERE clauses every business query applies. These tests run
those exact clauses against an in-memory SQLite table with the same column names as
`documents` / `conversations`, over a deliberately awkward population (two organizations,
two members and an administrator in one of them, private and shared documents, and rows with
no owner), so the rules are proven by what rows come back, including SQL's NULL behavior,
not by inspecting query text. The database-backed twin of this file is
tests/integration/test_data_isolation.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy import Enum, String, Uuid, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.auth.scope import AccessScope
from app.domain.enums.document_visibility import DocumentVisibility
from app.domain.models.conversation import Conversation
from app.domain.models.document import Document

PRIVATE = DocumentVisibility.PRIVATE
SHARED = DocumentVisibility.ORGANIZATION


class _Base(DeclarativeBase):
    pass


class _Doc(_Base):
    __tablename__ = "docs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    visibility: Mapped[DocumentVisibility] = mapped_column(
        Enum(
            DocumentVisibility,
            native_enum=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        )
    )


class _Conv(_Base):
    __tablename__ = "convs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


DOC = cast("type[Document]", _Doc)
CONV = cast("type[Conversation]", _Conv)

ORG_A, ORG_B = uuid.uuid4(), uuid.uuid4()


@dataclass(frozen=True)
class Person:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    is_admin: bool = False

    @property
    def scope(self) -> AccessScope:
        return AccessScope.for_user(
            user_id=self.user_id, organization_id=self.organization_id, is_admin=self.is_admin
        )


ALICE = Person(uuid.uuid4(), ORG_A)  # member of A
ALAN = Person(uuid.uuid4(), ORG_A)  # another member of A
ADA = Person(uuid.uuid4(), ORG_A, is_admin=True)  # administrator of A
BOB = Person(uuid.uuid4(), ORG_B)  # member of B
BEA = Person(uuid.uuid4(), ORG_B, is_admin=True)  # administrator of B

# (id, owner, visibility); an owner of None means a legacy, unassigned row.
DOCUMENTS = [
    ("alice-private", ALICE, PRIVATE),
    ("alice-shared", ALICE, SHARED),
    ("alan-private", ALAN, PRIVATE),
    ("alan-shared", ALAN, SHARED),
    ("bob-private", BOB, PRIVATE),
    ("bob-shared", BOB, SHARED),
    ("legacy-private", None, PRIVATE),
    ("legacy-shared", None, SHARED),
]
CONVERSATIONS = [
    ("alice-chat", ALICE),
    ("alan-chat", ALAN),
    ("ada-chat", ADA),
    ("bob-chat", BOB),
    ("legacy-chat", None),
]


@pytest.fixture(scope="module")
def session():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        for doc_id, owner, visibility in DOCUMENTS:
            db.add(
                _Doc(
                    id=doc_id,
                    organization_id=owner.organization_id if owner else None,
                    owner_user_id=owner.user_id if owner else None,
                    visibility=visibility,
                )
            )
        for conv_id, owner in CONVERSATIONS:
            db.add(
                _Conv(
                    id=conv_id,
                    organization_id=owner.organization_id if owner else None,
                    owner_user_id=owner.user_id if owner else None,
                )
            )
        db.commit()
        yield db


def _ids(db: Session, model: type, where) -> set[str]:
    return set(db.scalars(select(model.id).where(where)))


def readable(db: Session, scope: AccessScope) -> set[str]:
    return _ids(db, _Doc, scope.document_read_filter(DOC))


def manageable(db: Session, scope: AccessScope) -> set[str]:
    return _ids(db, _Doc, scope.document_manage_filter(DOC))


def summarized(db: Session, scope: AccessScope) -> set[str]:
    return _ids(db, _Doc, scope.document_summary_filter(DOC))


def owned(db: Session, scope: AccessScope) -> set[str]:
    return _ids(db, _Doc, scope.document_owner_filter(DOC))


def conversations(db: Session, scope: AccessScope) -> set[str]:
    return _ids(db, _Conv, scope.conversation_filter(CONV))


# -- reading documents ---------------------------------------------------------------


def test_a_member_reads_their_own_documents_and_their_organizations_shared_ones(session) -> None:
    assert readable(session, ALICE.scope) == {"alice-private", "alice-shared", "alan-shared"}


def test_a_member_never_reads_a_colleagues_private_document(session) -> None:
    assert "alan-private" not in readable(session, ALICE.scope)
    assert "alice-private" not in readable(session, ALAN.scope)


def test_an_administrator_reads_shared_documents_but_not_members_private_ones(session) -> None:
    # Being an administrator lets you manage documents (below), not read private ones.
    assert readable(session, ADA.scope) == {"alice-shared", "alan-shared"}


@pytest.mark.parametrize("person", [BOB, BEA])
def test_nothing_is_ever_readable_across_organizations(session, person: Person) -> None:
    seen = readable(session, person.scope)
    assert not seen & {"alice-private", "alice-shared", "alan-private", "alan-shared"}


def test_documents_with_no_owner_are_invisible_to_everyone(session) -> None:
    for person in (ALICE, ALAN, ADA, BOB, BEA):
        assert not readable(session, person.scope) & {"legacy-private", "legacy-shared"}


# -- deleting / re-sharing documents -------------------------------------------------


def test_a_member_manages_only_their_own_documents(session) -> None:
    assert manageable(session, ALICE.scope) == {"alice-private", "alice-shared"}


def test_an_administrator_manages_every_document_in_their_organization_only(session) -> None:
    assert manageable(session, ADA.scope) == {
        "alice-private",
        "alice-shared",
        "alan-private",
        "alan-shared",
    }
    assert manageable(session, BEA.scope) == {"bob-private", "bob-shared"}


def test_nobody_manages_unowned_documents(session) -> None:
    for person in (ALICE, ADA, BOB, BEA):
        assert not manageable(session, person.scope) & {"legacy-private", "legacy-shared"}


# -- the operations summary ----------------------------------------------------------


def test_a_members_summary_covers_only_what_they_may_read(session) -> None:
    assert summarized(session, ALICE.scope) == readable(session, ALICE.scope)
    assert summarized(session, ALICE.scope) == {"alice-private", "alice-shared", "alan-shared"}


def test_an_administrators_summary_covers_their_whole_organization_and_nothing_else(
    session,
) -> None:
    # Aggregate counts only (no titles, owners or content), so this reveals no private document.
    assert summarized(session, ADA.scope) == {
        "alice-private",
        "alice-shared",
        "alan-private",
        "alan-shared",
    }
    assert summarized(session, BEA.scope) == {"bob-private", "bob-shared"}


def test_no_summary_ever_includes_another_organization_or_unowned_rows(session) -> None:
    for person in (ALICE, ALAN, ADA, BOB, BEA):
        counted = summarized(session, person.scope)
        assert not counted & {"legacy-private", "legacy-shared"}
    assert not summarized(session, ADA.scope) & {"bob-private", "bob-shared"}
    assert not summarized(session, BEA.scope) & {"alice-shared", "alan-shared"}


# -- duplicate detection -------------------------------------------------------------


def test_duplicate_detection_only_ever_sees_the_callers_own_documents(session) -> None:
    assert owned(session, ALICE.scope) == {"alice-private", "alice-shared"}
    assert owned(session, ADA.scope) == set()  # an administrator owns nothing here
    assert not owned(session, ALICE.scope) & {"alan-shared", "bob-shared", "legacy-shared"}


# -- conversations -------------------------------------------------------------------


def test_a_conversation_is_visible_to_its_owner_alone(session) -> None:
    assert conversations(session, ALICE.scope) == {"alice-chat"}
    assert conversations(session, ALAN.scope) == {"alan-chat"}
    assert conversations(session, BOB.scope) == {"bob-chat"}


def test_an_administrator_has_no_special_access_to_conversations(session) -> None:
    assert conversations(session, ADA.scope) == {"ada-chat"}
    assert conversations(session, BEA.scope) == set()


def test_unowned_conversations_are_invisible_to_everyone(session) -> None:
    for person in (ALICE, ALAN, ADA, BOB, BEA):
        assert "legacy-chat" not in conversations(session, person.scope)


# -- degenerate scopes ---------------------------------------------------------------


def test_a_scope_without_a_user_matches_nothing() -> None:
    empty = AccessScope(user_id=None, organization_id=None)
    with Session(create_engine("sqlite://")) as db:
        _Base.metadata.create_all(db.get_bind())
        db.add(_Doc(id="x", organization_id=ORG_A, owner_user_id=ALICE.user_id, visibility=SHARED))
        db.add(_Conv(id="c", organization_id=ORG_A, owner_user_id=ALICE.user_id))
        db.commit()
        assert readable(db, empty) == set()
        assert manageable(db, empty) == set()
        assert owned(db, empty) == set()
        assert summarized(db, empty) == set()
        assert conversations(db, empty) == set()


def test_only_the_explicit_operator_scope_is_unrestricted(session) -> None:
    operator = AccessScope.unrestricted_for_operators()

    assert len(readable(session, operator)) == len(DOCUMENTS)
    assert len(conversations(session, operator)) == len(CONVERSATIONS)
    # A request-derived scope is never unrestricted, whatever the role.
    for person in (ALICE, ADA, BEA):
        assert person.scope.unrestricted is False


def test_the_unrestricted_scope_cannot_be_built_from_a_principal() -> None:
    from app.auth.principal import Principal
    from app.domain.enums.user_role import UserRole

    scope = AccessScope.from_principal(
        Principal(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            role=UserRole.ADMIN,
            email="a@example.test",
            issuer="https://idp.example.test/realms/aegis",
        )
    )

    assert scope.unrestricted is False and scope.is_admin is True
