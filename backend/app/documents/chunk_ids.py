"""Deterministic chunk identifiers.

A chunk's id is derived — via UUID5 (RFC 4122), not randomly assigned via
UUID4 — from the source document's content checksum plus the chunking
configuration that produced it. Reprocessing the same file content with the
same chunk size/overlap always yields the same set of chunk ids; changing
either the content or the chunking configuration yields a different set.

This is deliberate, not incidental: the next milestone (embeddings) needs a
stable way to ask "has this exact chunk already been embedded?", and a
random id would make that impossible without extra bookkeeping. UUID5 is
the standard, well-defined way to get a deterministic identifier that still
behaves like a UUID for schema/column-type purposes — not an ad hoc hash
repurposed as one.
"""

import uuid

# A fixed, arbitrary namespace UUID for this application's chunk ids,
# generated once (uuid4()) and never changed — changing it would silently
# reassign every chunk a new id on next reprocessing.
_CHUNK_ID_NAMESPACE = uuid.UUID("7f3b8e2a-6c4d-4b1a-9e2f-5a8d6c3b1e9f")


def compute_chunk_id(
    *,
    document_checksum: str,
    chunk_size: int,
    chunk_overlap: int,
    chunk_index: int,
) -> uuid.UUID:
    name = f"{document_checksum}:{chunk_size}:{chunk_overlap}:{chunk_index}"
    return uuid.uuid5(_CHUNK_ID_NAMESPACE, name)
