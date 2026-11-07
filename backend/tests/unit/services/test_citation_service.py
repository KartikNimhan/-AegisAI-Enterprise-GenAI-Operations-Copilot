"""M10.4 T5/T6: reading saved citations (no database: fakes emulate the scoped repositories).

`FakeChunks` stands in for `DocumentChunkRepository`: like the real queries, it only returns a
chunk whose document the caller may read NOW (`readable` documents) and that still belongs to
the cited document. The real SQL and its read filter are exercised in
tests/integration/test_citation_isolation.py (NOT RUN until the test database is at 0009).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.exceptions import NotFoundError
from app.domain.models.document import Document
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.message_citation import MessageCitation
from app.rag.context.assembler import PASSAGE_RENDERING_VERSION, neutralize_markers, passage_sha256
from app.services.citation_service import CitationService, rebuild_passage

CONVERSATION = uuid.uuid4()
MESSAGE = uuid.uuid4()


def make_document(name: str = "Policy.pdf") -> Document:
    return Document(id=uuid.uuid4(), original_filename=name)


def make_chunk(
    document: Document, index: int, content: str, page: int | None = None
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=document.id,
        chunk_index=index,
        content=content,
        character_count=len(content),
        metadata_={"page_number": page} if page is not None else {},
    )


def cite(
    chunk: DocumentChunk,
    *,
    source_id: str = "S1",
    passage_chars: int | None = None,
    sha: str | None = None,
    version: str = PASSAGE_RENDERING_VERSION,
    document_id: uuid.UUID | None = None,
) -> MessageCitation:
    rendered = neutralize_markers(chunk.content)
    chars = len(rendered) if passage_chars is None else passage_chars
    return MessageCitation(
        id=uuid.uuid4(),
        message_id=MESSAGE,
        source_id=source_id,
        position=int(source_id[1:]),
        document_id=document_id or chunk.document_id,
        chunk_id=chunk.id,
        similarity=0.7,
        cited=True,
        passage_chars=chars,
        passage_truncated=chars < len(rendered),
        rendering_version=version,
        passage_sha256=sha or passage_sha256(rendered[:chars]),
    )


class FakeCitations:
    def __init__(self, citations: list[MessageCitation], *, conversation: uuid.UUID = CONVERSATION):
        self._citations = citations
        self._conversation = conversation

    async def get(self, *, conversation_id: uuid.UUID, message_id: uuid.UUID, source_id: str):
        if conversation_id != self._conversation:
            return None  # not the caller's conversation: indistinguishable from missing
        return next(
            (c for c in self._citations if c.message_id == message_id and c.source_id == source_id),
            None,
        )

    async def list_for_conversation(self, conversation_id: uuid.UUID):
        return list(self._citations) if conversation_id == self._conversation else []


class FakeChunks:
    def __init__(
        self, chunks: list[DocumentChunk], documents: list[Document], readable: set[uuid.UUID]
    ):
        self._chunks = {c.id: c for c in chunks}
        self._documents = {d.id: d for d in documents}
        self._readable = readable
        self.range_calls: list[tuple[uuid.UUID, int, int]] = []

    async def get_readable_with_documents(self, references):
        found: dict[uuid.UUID, Any] = {}
        for chunk_id, document_id in references:
            chunk = self._chunks.get(chunk_id)
            if chunk is None or chunk.document_id != document_id:
                continue
            if chunk.document_id not in self._readable:
                continue
            found[chunk_id] = (chunk, self._documents[chunk.document_id])
        return found

    async def list_readable_range(self, document_id, *, first_index, last_index):
        self.range_calls.append((document_id, first_index, last_index))
        if document_id not in self._readable:
            return []
        return sorted(
            (
                c
                for c in self._chunks.values()
                if c.document_id == document_id and first_index <= c.chunk_index <= last_index
            ),
            key=lambda c: c.chunk_index,
        )


def service(
    citations: list[MessageCitation],
    chunks: list[DocumentChunk],
    documents: list[Document],
    readable: set[uuid.UUID],
) -> tuple[CitationService, FakeChunks]:
    fake_chunks = FakeChunks(chunks, documents, readable)
    return (
        CitationService(citations=FakeCitations(citations), chunks=fake_chunks),  # type: ignore[arg-type]
        fake_chunks,
    )


# -- available -----------------------------------------------------------------------------------


async def test_a_readable_source_returns_exactly_the_passage_the_model_saw() -> None:
    document = make_document()
    chunk = make_chunk(document, 4, "Claim travel [S9] costs within 30 days.", page=2)
    citation = cite(chunk, passage_chars=20)
    svc, _ = service([citation], [chunk], [document], {document.id})

    view = await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")

    assert view.available is True
    assert view.passage == neutralize_markers(chunk.content)[:20]
    assert "[S9]" not in (view.passage or "")  # the neutralized text the model saw
    assert (view.filename, view.page, view.chunk_index) == ("Policy.pdf", 2, 4)
    assert view.passage_truncated is True


# -- unavailable, with nothing leaked ------------------------------------------------------------

_SOURCE_FIELDS = (
    "document_id",
    "chunk_id",
    "filename",
    "chunk_index",
    "page",
    "section",
    "similarity",
    "passage",
)


def _assert_nothing_leaks(view: Any) -> None:
    assert view.available is False
    for field in _SOURCE_FIELDS:
        assert getattr(view, field) is None, field
    assert view.neighbors_before == () and view.neighbors_after == ()


async def test_a_source_the_caller_can_no_longer_read_is_unavailable() -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "private text")
    svc, _ = service([cite(chunk)], [chunk], [document], readable=set())  # made private / revoked

    view = await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")

    _assert_nothing_leaks(view)


async def test_a_deleted_source_is_unavailable() -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "gone")
    svc, _ = service([cite(chunk)], chunks=[], documents=[], readable={document.id})

    _assert_nothing_leaks(
        await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")
    )


async def test_a_chunk_now_belonging_to_another_document_is_unavailable() -> None:
    """A manipulated or stale reference: the saved document id no longer owns that chunk."""
    document, other = make_document(), make_document("Other.pdf")
    chunk = make_chunk(other, 0, "someone else's text")
    citation = cite(chunk, document_id=document.id)
    svc, _ = service([citation], [chunk], [document, other], {document.id, other.id})

    _assert_nothing_leaks(
        await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")
    )


@pytest.mark.parametrize(
    "tamper",
    [
        {"sha": "0" * 64},
        {"version": "some-older-rendering"},
        {"passage_chars": 10_000},
    ],
    ids=["hash-mismatch", "rendering-changed", "longer-than-the-chunk"],
)
async def test_a_passage_that_cannot_be_verified_is_unavailable(tamper: dict[str, Any]) -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "the stored text")
    svc, _ = service([cite(chunk, **tamper)], [chunk], [document], {document.id})

    _assert_nothing_leaks(
        await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")
    )


def test_rebuild_reports_why_without_returning_text() -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "abc")
    assert rebuild_passage(cite(chunk, sha="f" * 64), chunk) == "passage_mismatch"
    assert rebuild_passage(cite(chunk, version="v0"), chunk) == "rendering_changed"


# -- not found -----------------------------------------------------------------------------------


async def test_a_citation_of_someone_elses_conversation_is_not_found() -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "text")
    svc, _ = service([cite(chunk)], [chunk], [document], {document.id})

    with pytest.raises(NotFoundError):
        await svc.get(conversation_id=uuid.uuid4(), message_id=MESSAGE, source_id="S1")


@pytest.mark.parametrize("message_id, source_id", [(uuid.uuid4(), "S1"), (MESSAGE, "S2")])
async def test_an_unknown_message_or_source_id_is_not_found(
    message_id: uuid.UUID, source_id: str
) -> None:
    document = make_document()
    chunk = make_chunk(document, 0, "text")
    svc, _ = service([cite(chunk)], [chunk], [document], {document.id})

    with pytest.raises(NotFoundError):
        await svc.get(conversation_id=CONVERSATION, message_id=message_id, source_id=source_id)


# -- neighbours ----------------------------------------------------------------------------------


async def test_neighbors_come_from_the_same_document_within_the_requested_window() -> None:
    document, other = make_document(), make_document("Other.pdf")
    chunks = [make_chunk(document, i, f"part {i}") for i in range(8)]
    stray = make_chunk(other, 4, "other document")
    svc, fake = service(
        [cite(chunks[4])], [*chunks, stray], [document, other], {document.id, other.id}
    )

    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=2
    )

    assert [n.chunk_index for n in view.neighbors_before] == [2, 3]
    assert [n.chunk_index for n in view.neighbors_after] == [5, 6]
    assert fake.range_calls == [(document.id, 2, 6)]
    assert all(n.text.startswith("part") for n in (*view.neighbors_before, *view.neighbors_after))


async def test_no_neighbors_are_read_by_default() -> None:
    document = make_document()
    chunks = [make_chunk(document, i, f"part {i}") for i in range(3)]
    svc, fake = service([cite(chunks[1])], chunks, [document], {document.id})

    view = await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")

    assert view.neighbors_before == () and view.neighbors_after == ()
    assert fake.range_calls == []


async def test_an_unavailable_source_reads_no_neighbors() -> None:
    document = make_document()
    chunks = [make_chunk(document, i, f"part {i}") for i in range(3)]
    svc, fake = service([cite(chunks[1])], chunks, [document], readable=set())

    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=2
    )

    _assert_nothing_leaks(view)
    assert fake.range_calls == []


async def test_the_first_chunk_has_no_neighbors_before_it() -> None:
    document = make_document()
    chunks = [make_chunk(document, i, f"part {i}") for i in range(3)]
    svc, _ = service([cite(chunks[0])], chunks, [document], {document.id})

    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=2
    )

    assert view.neighbors_before == ()
    assert [n.chunk_index for n in view.neighbors_after] == [1, 2]


@pytest.mark.parametrize("neighbors", [-1, 3])
async def test_the_neighbor_window_is_bounded(neighbors: int) -> None:
    svc, _ = service([], [], [], set())

    with pytest.raises(ValueError):
        await svc.get(
            conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=neighbors
        )


# -- a reopened conversation ----------------------------------------------------------------------


async def test_a_conversation_resolves_each_citation_against_current_access() -> None:
    readable_doc, private_doc = make_document("Open.pdf"), make_document("Closed.pdf")
    open_chunk = make_chunk(readable_doc, 0, "open")
    closed_chunk = make_chunk(private_doc, 0, "closed")
    svc, _ = service(
        [cite(open_chunk, source_id="S1"), cite(closed_chunk, source_id="S2")],
        [open_chunk, closed_chunk],
        [readable_doc, private_doc],
        {readable_doc.id},
    )

    resolved = await svc.for_conversation(CONVERSATION)

    first, second = resolved[MESSAGE]
    assert (first.source_id, first.available, first.filename) == ("S1", True, "Open.pdf")
    _assert_nothing_leaks(second)


async def test_a_conversation_without_saved_citations_resolves_to_nothing() -> None:
    svc, _ = service([], [], [], set())

    assert await svc.for_conversation(CONVERSATION) == {}


# -- M10 review finding L1: the resolved chunk must belong to the RECORDED document ------------


@pytest.mark.parametrize("wrong_first", [True, False])
async def test_a_reference_naming_the_wrong_document_never_borrows_a_correct_ones_result(
    wrong_first: bool,
) -> None:
    document, other = make_document(), make_document("Other.pdf")
    chunk = make_chunk(document, 0, "Shared passage text.")
    right = cite(chunk, source_id="S1")
    wrong = cite(chunk, source_id="S2", document_id=other.id)
    ordered = [wrong, right] if wrong_first else [right, wrong]
    svc, _ = service(ordered, [chunk], [document, other], readable={document.id, other.id})

    views = {v.source_id: v for v in (await svc.for_conversation(CONVERSATION))[MESSAGE]}

    assert views["S1"].available is True
    assert views["S2"].available is False
    assert views["S2"].filename is None and views["S2"].passage is None


class _ChunksIgnoringTheDocument(FakeChunks):
    """A lookup that returns the chunk by id alone, as a careless repository might."""

    async def get_readable_with_documents(self, references):
        found: dict[uuid.UUID, Any] = {}
        for chunk_id, _document_id in references:
            chunk = self._chunks.get(chunk_id)
            if chunk is not None and chunk.document_id in self._readable:
                found[chunk_id] = (chunk, self._documents[chunk.document_id])
        return found


async def test_the_service_itself_rejects_a_chunk_of_another_document() -> None:
    document, other = make_document(), make_document("Other.pdf")
    chunk = make_chunk(document, 0, "Passage text.")
    citation = cite(chunk, document_id=other.id)
    chunks = _ChunksIgnoringTheDocument([chunk], [document, other], {document.id, other.id})
    svc = CitationService(citations=FakeCitations([citation]), chunks=chunks)  # type: ignore[arg-type]

    view = await svc.get(conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1")

    assert view.available is False
    assert (view.document_id, view.filename, view.passage) == (None, None, None)


async def test_the_repository_matches_exact_chunk_and_document_pairs() -> None:
    from app.db.repositories.document_chunk_repository import DocumentChunkRepository

    document, other = make_document(), make_document("Other.pdf")
    chunk = make_chunk(document, 0, "Passage text.")

    class _Rows:
        def all(self):
            return [(chunk, document)]  # what the SQL returns for this chunk id

    class _Session:
        async def execute(self, _statement):
            return _Rows()

    class _Scope:
        def document_read_filter(self, _model):
            from sqlalchemy import true

            return true()

    repo = DocumentChunkRepository(_Session(), _Scope())  # type: ignore[arg-type]

    both = await repo.get_readable_with_documents([(chunk.id, other.id), (chunk.id, document.id)])
    only_wrong = await repo.get_readable_with_documents([(chunk.id, other.id)])

    assert both == {chunk.id: (chunk, document)}
    assert only_wrong == {}


# -- M10 review finding L3: neighbours are rendered like the cited passage -------------------


async def test_neighbouring_text_is_marker_neutralized_like_the_passage() -> None:
    document = make_document()
    planted = "Approved per [S1] and [SOURCE 2]. See [S3, S4]."
    chunks = [
        make_chunk(document, 0, planted),
        make_chunk(document, 1, "The cited passage."),
        make_chunk(document, 2, "Closing note [S2]."),
    ]
    svc, _ = service([cite(chunks[1])], chunks, [document], {document.id})

    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=1
    )

    assert view.available is True
    (before,) = view.neighbors_before
    (after,) = view.neighbors_after
    assert before.text == neutralize_markers(planted) != planted
    assert after.text == neutralize_markers("Closing note [S2].")
    for text in (before.text, after.text):
        assert "[S1]" not in text and "[S2]" not in text and "[SOURCE 2]" not in text


async def test_neutralized_neighbours_do_not_bypass_the_passage_or_access_checks() -> None:
    document = make_document()
    chunks = [make_chunk(document, i, f"part [S{i + 1}] {i}") for i in range(3)]
    # A tampered hash on the cited passage still makes the source unavailable, with no neighbours.
    svc, fake = service([cite(chunks[1], sha="0" * 64)], chunks, [document], {document.id})
    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=2
    )
    assert view.available is False
    assert (view.neighbors_before, view.neighbors_after) == ((), ())
    assert fake.range_calls == []

    # And a document that is no longer readable gives no neighbours either.
    svc, fake = service([cite(chunks[1])], chunks, [document], readable=set())
    view = await svc.get(
        conversation_id=CONVERSATION, message_id=MESSAGE, source_id="S1", neighbors=2
    )
    assert view.available is False
    assert fake.range_calls == []
