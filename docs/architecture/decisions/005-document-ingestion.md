# 5. Document Ingestion: Storage, Extraction, Chunking, and Lifecycle

## Status

Accepted — 2026-10-03

(Numbered 005, not 004 as originally suggested when this milestone was
scoped — 004 was already used by
[004-conversation-persistence.md](004-conversation-persistence.md) from
Milestone 2.)

## Context

Milestone 3 builds the document intelligence and ingestion foundation that
Milestone 4 (embeddings) will consume: upload, validate, store, extract,
normalize, chunk, and persist — explicitly **not** embeddings, vector
search, RAG retrieval, or any agent/MCP/A2A concern. Every chunk this
milestone produces must be independently embeddable later without a
rewrite of this pipeline.

## Decision

### Pipeline and module boundaries

```
API (api/v1/documents.py)
  -> DocumentService (orchestration)
    -> app.documents.validation   (extension/MIME/size/magic-byte checks)
    -> app.storage                (provider-neutral file storage; LocalFileStorage for now)
    -> app.documents.extractors   (one module per DocumentType; pypdf, python-docx)
    -> app.documents.normalization
    -> app.documents.metadata
    -> app.documents.chunking     (RecursiveChunker)
    -> db.repositories.{document,document_chunk}_repository
```

Each stage is its own small, independently testable module —
`DocumentService` orchestrates but contains no parsing, chunking, or SQL
logic itself, mirroring `ChatService`'s role from Milestone 2.

### Document lifecycle: four states, not one per pipeline stage

`DocumentStatus`: `UPLOADED -> PROCESSING -> PROCESSED | FAILED`. The task
brief sketched a finer-grained flow (`EXTRACTION -> NORMALIZATION ->
CHUNKING -> PERSIST`) as sub-steps; those are **not** separate persisted
statuses. Reasoning: this milestone processes synchronously, within one
request — those sub-steps complete in milliseconds and are never
independently observable or queryable by anything outside the request
that's already waiting on its response. A finer-grained enum would add
schema and code surface with no present operational value. If/when
processing moves to a background worker (see below), the sub-steps still
won't need their own top-level status — a worker can log/report progress
without the document's lifecycle model needing to expose it.

### Two commits, not one — a deliberate difference from ChatService

`ChatService` (Milestone 2) commits once per request: if anything fails,
the whole turn — including the user's message — is discarded, because an
LLM failure means nothing useful happened yet. Document ingestion is
different: by the time processing could fail, **the file is already
durably on disk** and the upload itself succeeded. `DocumentService`
therefore commits twice:

1. After validation + storage: the `Document` row is committed with status
   `UPLOADED`.
2. After processing (extract/normalize/chunk/persist): a second commit
   lands status `PROCESSED` (with chunks) or `FAILED` (with a safe
   `error_message`, no chunks).

If chunk persistence itself fails after chunking succeeds, it's wrapped in
`session.begin_nested()` (a `SAVEPOINT`) — only the failed chunk insert
rolls back, not the `UPLOADED` document row already pending in the same
transaction. This guarantees: **a document record always exists after a
successful upload, in exactly one of `PROCESSED` or `FAILED`, and
`FAILED` never leaves partial chunks behind.**

This is also, deliberately, the seam a future background worker would
split along: step 1 (accept the upload) and step 2 (process it) are
already two independent operations against a `Document` already in
`UPLOADED` — see "Future background-processing design" below.

### An unexpected correctness lesson: don't mix clock sources

While building this, an existing Milestone 2 test
(`test_list_orders_by_most_recently_updated`) started failing
intermittently. Root cause: `ConversationRepository.touch()` sets
`updated_at` using the **application process's** clock
(`datetime.now(UTC)`), while `created_at` came from **Postgres's** clock
(`server_default=func.now()`). Under a few milliseconds of clock skew
between the two processes (reproducible running Postgres in Docker Desktop
on Windows), a conversation touched microseconds after another was created
could still show an *earlier* `updated_at`. Separately, Windows' clock
resolution (as coarse as ~15ms) means two timestamps captured
microseconds apart in real time can be bit-for-bit identical — a genuine
tie, not a bug, but one that needs a deterministic tiebreaker.

Both `Conversation` and the new `Document`/`DocumentChunk` models now use
an ORM-level `default=lambda: datetime.now(UTC)` alongside
`server_default=func.now()` (the latter remains as a DB-level fallback for
non-ORM inserts) — keeping every app-managed timestamp on *one* clock, so
values that are supposed to compare consistently, do. `list()` queries
additionally sort with a secondary `id DESC` tiebreaker for deterministic
pagination when timestamps genuinely tie. This is noted here because it's
a general pattern, not a document-ingestion-specific one, in case it comes
up again when the next milestone adds its own timestamped, touchable model.

### Storage: provider-neutral, local filesystem for now

`app.storage.base.DocumentStorage` is a 4-method interface (`save`, `read`,
`delete`, `exists`) keyed by an opaque string. `LocalFileStorage` is the
only implementation, storing files under `Settings.document_storage_dir`
(default: `data/uploads/` at the repo root — outside `backend/app`,
matching the existing `data/` convention from Milestone 0). File I/O is
offloaded via `asyncio.to_thread` so it doesn't block the event loop. The
storage key is always `f"{document.id}{extension}"` — generated from the
document's own id, never from the client's filename — which is also why
path traversal isn't just validated against but structurally impossible:
nothing client-supplied ever reaches a filesystem path. Docker Compose
bind-mounts `./data/uploads` into the container at the same path the
config resolves to, so uploads land in the same place and survive
container recreation, matching Postgres's `pgdata` volume.

Adding S3/Azure Blob/GCS later means implementing `DocumentStorage` in a
new module — no change to `DocumentService` or the API.

### Validation: layered, trusting no single signal

Extension, declared `Content-Type`, and (where a format has one) a magic-
byte signature are all checked independently — any one being spoofed isn't
enough to get past the others. The upload body is read with a bounded
`file.read(max_size + 1)`, so an oversized upload is rejected without ever
buffering more than `max_size + 1` bytes in memory, regardless of what the
client claims or attempts to send.

### Extraction: one library per format, isolated

- **PDF**: [`pypdf`](https://pypi.org/project/pypdf/) (pure Python, MIT
  licensed, actively maintained — v6.x as of this milestone). Extracts
  page-by-page, keeping `page_count` and (via the chunker) per-chunk page
  attribution.
- **DOCX**: [`python-docx`](https://pypi.org/project/python-docx/) (the
  standard library for this, v1.2.x). Extracts paragraph text and
  paragraph counts.
- **TXT/Markdown**: no dependency — a short, deterministic encoding
  fallback chain (`utf-8-sig` on a detected BOM, else `utf-8`, `cp1252`,
  then `latin-1`, which never raises). No `chardet`/`charset-normalizer`
  dependency, and no network-fetched encoding data.

A library failing to parse a file at all (`pypdf`/`python-docx` raising)
is translated to `ExtractionError` and caught by `DocumentService`, landing
the document in `FAILED`. A file that parses successfully but yields no
text (e.g. an image-only PDF — OCR is explicitly out of scope this
milestone) is treated the same way: `FAILED` with a clear message, never a
silently-empty `PROCESSED` document with zero chunks.

### Normalization: conservative, not a rewrite

Line-ending normalization, horizontal-whitespace collapsing, trailing-
whitespace stripping, excessive-blank-line collapsing, BOM stripping, and
Unicode NFC canonicalization. Deliberately does **not** touch single line
breaks (which may be meaningful — code blocks, lists, poetry) or reflow
paragraphs.

### Chunking: recursive/structure-aware, character-based, per-page

`RecursiveChunker` splits on the first available separator
(`\n\n`, `\n`, `. `, " ", then a hard character window as the final
fallback), recursing into any piece still over `chunk_size`, then greedily
merges small pieces back up to `chunk_size` with `chunk_overlap` characters
carried from the end of one chunk into the start of the next. No external
chunking framework (e.g. LangChain's text splitters) — the algorithm is
the same well-known shape, reimplemented directly so this module has no
dependency on it.

**Chunking is char-based, not token-based**, and `DocumentChunk.token_count`
is left `None` in this milestone. A token count is only meaningful relative
to a specific tokenizer, and no embedding model (with a specific, known
tokenizer) has been chosen yet — that's Milestone 4's decision. Adding a
generic tokenizer now (e.g. `tiktoken`) was considered and rejected: its
default encodings are fetched over the network on first use, which is a
poor fit for an otherwise fully offline, deterministic pipeline, and an
approximate count under the wrong tokenizer would be worse than an honest
`None`.

**Each chunk belongs to exactly one page** — chunking runs independently
per page rather than on the whole document's concatenated text. For
multi-page PDFs this means every chunk has an exact, unambiguous
`page_number` (vs. a possibly-ambiguous range for a chunk spanning a page
boundary), which matters more for traceability than saving the handful of
chunks that would otherwise straddle a boundary. Single-page documents
(DOCX/TXT/Markdown) carry no `page_number` at all — "page" isn't a
meaningful concept for them.

### Deterministic chunk identifiers

`DocumentChunk.id` is a UUID5 (RFC 4122, not a random UUID4) derived from
`document.checksum + chunk_size + chunk_overlap + chunk_index` (see
`app.documents.chunk_ids.compute_chunk_id`). Reprocessing identical content
with identical chunking configuration always reproduces identical chunk
ids; changing either the content or the configuration produces a different
set. This is intentional, not an accident of implementation — Milestone 4
needs a stable way to ask "has this exact chunk already been embedded?",
and a random id would make that impossible without extra bookkeeping. Note
this is **not** the same mechanism as duplicate *document* detection
(checksum lookup, below) — it's specifically about chunk-level
reproducibility once processing actually runs.

### Duplicate detection: return the existing document, do no new work

`Document.checksum` (SHA-256 of the raw uploaded bytes) is looked up
*before* any storage or processing. A match returns the existing document
(`is_duplicate: true` in the API response, HTTP `200` rather than `201`,
since nothing new was created) — the file is not re-stored and reprocessed.
This is a service-layer decision (look up, then decide), not a database
uniqueness constraint, so it's explicit and easy to change later (e.g., to
"reject outright" or "version it") without a schema migration. Known,
accepted limitation: two uploads of identical content racing concurrently
could both pass the lookup and each create a document — acceptable for
this milestone's synchronous, single-request-at-a-time scope; a unique
constraint could close this gap later if it matters in practice.

### Synchronous processing: a stated, not hidden, tradeoff

Processing happens inline within the upload request. This is explicitly
not production-scalable for large files or high upload volume — a slow
extraction blocks that request (and, since `asyncio.to_thread` is used,
ties up a thread-pool worker) for its duration. It was chosen for this
milestone because the brief calls for it and because `DocumentService`'s
two-phase commit structure (above) is already shaped the way a background
split needs it to be.

**Future background-processing design** (not implemented): a worker would
poll for `Document` rows in `UPLOADED` (or a dedicated queue message
produced at upload time), call the equivalent of
`DocumentService._process()` directly, and commit the outcome — no change
to the `DocumentService` internals, the schema, or the upload API's
contract. The upload endpoint would change from "wait for processing, return
the final status" to "return `201` with status `UPLOADED` immediately,"
with the existing `GET /api/v1/documents/{id}` endpoint already sufficient
for the client to poll for completion.

## Consequences

- **Positive**: every module in the pipeline (validation, storage,
  extraction, normalization, chunking) is independently unit-testable with
  no database or network dependency; only persistence itself needs real
  Postgres.
- **Positive**: a `FAILED` document is never a mystery — it's retrievable,
  carries a safe diagnostic message, and definitely has zero chunks.
- **Positive**: chunk determinism and page-exact attribution are both
  directly useful for Milestone 4 without any rework.
- **Negative**: synchronous processing means upload latency scales with
  file size and format complexity; a large PDF genuinely makes the client
  wait. Explicitly out of scope to fix here.
- **Negative**: char-based chunk sizing is an approximation of what will
  eventually matter (token-based limits for a specific embedding model) —
  revisit once Milestone 4 picks that model.

## Related

- [001-modular-monolith.md](001-modular-monolith.md)
- [004-conversation-persistence.md](004-conversation-persistence.md) (the
  atomic-transaction pattern this ADR deliberately departs from, and why)
