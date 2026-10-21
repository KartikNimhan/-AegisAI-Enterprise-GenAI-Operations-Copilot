"""Deterministic chunk identifiers.

A chunk's id is derived — via UUID5 (RFC 4122), not randomly assigned via
UUID4 — from the id of the document it belongs to plus the chunking
configuration that produced it. Re-chunking the same document with the same
chunk size/overlap always yields the same set of chunk ids; changing either the
document or the chunking configuration yields a different set.

This is deliberate, not incidental: embeddings need a stable way to ask "has
this exact chunk already been embedded?", and a random id would make that
impossible without extra bookkeeping. UUID5 is the standard, well-defined way to
get a deterministic identifier that still behaves like a UUID for schema/column-
type purposes — not an ad hoc hash repurposed as one.

The document id (not its content checksum) is the input because documents are
owned: two users may upload byte-identical files and each gets their own
document, and their chunks must not share a primary key. (Earlier versions used
the content checksum, which is only safe while every identical upload is merged
into one global document.)
"""

import uuid

_CHUNK_ID_NAMESPACE = uuid.UUID("7f3b8e2a-6c4d-4b1a-9e2f-5a8d6c3b1e9f")


def compute_chunk_id(
    *,
    document_id: uuid.UUID,
    chunk_size: int,
    chunk_overlap: int,
    chunk_index: int,
) -> uuid.UUID:
    name = f"{document_id}:{chunk_size}:{chunk_overlap}:{chunk_index}"
    return uuid.uuid5(_CHUNK_ID_NAMESPACE, name)
