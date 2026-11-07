# 18. Citation Persistence and Passage Retrieval (M10.4)

## Status

Accepted by the owner — 2026-11-03 (decisions); implemented locally 2026-11-03. Migration `0009` is
written and checked offline only; it has **not** been applied to any database.

## Context

Before M10.4 a RAG answer's `[S1]`-style markers pointed at sources that existed only in the HTTP
response. A reopened conversation could not resolve them, the response carried no chunk id, and
nothing recorded which exact text the model had been given (the context assembler rewrites marker
look-alikes and may cut the first source to fit the budget).

## Decision

1. **References, not text.** A separate `message_citations` table holds one row per source of an
   assistant answer: `source_id`/`position` (`S1` = 1), `document_id`, `chunk_id`, `similarity`,
   `cited`, `passage_chars`, `passage_truncated`, `rendering_version`, `passage_sha256`. No
   document text is stored.
2. **Foreign keys.** `message_id` → `messages.id` `ON DELETE CASCADE` (deleting a conversation
   deletes its citations). `document_id` and `chunk_id` have **no** foreign key: a reference
   survives the document's deletion and reads as unavailable. Retention is subject to the M9.5
   policy.
3. **Exact passage.** The assembler records how many characters of the chunk's neutralized text
   the model saw and the SHA-256 of exactly that passage. Chunks are immutable, so
   `neutralize_markers(content)[:passage_chars]` rebuilds it; a read verifies the rendering version
   (`neutralize-markers-v1`) and the hash, and treats any mismatch as unavailable.
4. **Similarity.** `CHECK (similarity BETWEEN -1.0 AND 1.0)`. The writer rejects non-finite scores
   (never converting them into valid ones) and clamps finite ones into the range, because
   pgvector's server-side rounding can't be ruled out from this repository and its image is not
   pinned. A NaN score never reaches the writer: it fails the retrieval threshold.
5. **Saving.** Citation records are built before the model is called (a broken invariant fails the
   request before tokens are spent) and saved in the same transaction as the assistant message. The
   streaming path fixes the message id up front and reports it on the final event; the reply is
   saved after the final chunk.
   **Commit before `[DONE]` (guarantee added 2026-11-04, M10 review finding M1):**
   - `RAGService` commits the reply and its citations itself, before the generator ends, so the
     route sends `[DONE]` only after the commit. The JSON answer is likewise committed before its
     `message_id` is returned (ADR 007, "Commit ownership").
   - So a client may open a citation as soon as it has `[DONE]` (or the JSON answer).
   - If the commit fails, no `[DONE]` is sent, and the request session is expected to roll back
     (shown with test doubles only; not yet verified against a real database, see ADR 007).
   - **`[DONE]` confirms the reply; its absence does not prove that nothing was saved.** The
     commit happens just before `[DONE]` is sent. A connection lost in between (or a `[DONE]`
     lost in transit) leaves a committed reply that the client never saw confirmed. The client
     therefore treats a stream without `[DONE]` as **unconfirmed**: it shows the error and
     discards the `message_id`, so no citation is opened from it. If the reply was in fact saved,
     it appears, with its citations, when the conversation is reopened.
   - Before this, the request session committed only after the response had been sent, so
     `[DONE]` could precede the commit.
6. **Reading.** `GET /api/v1/conversations/{conversation_id}/messages/{message_id}/citations/{source_id}?neighbors=0..2`
   - the conversation must be the caller's (`conversation_filter`); otherwise 404, like any
     resource;
   - the chunk is read through the CURRENT document read filter and must still belong to the cited
     document;
   - anything that fails (deleted, made private, foreign, re-chunked, hash or rendering mismatch)
     returns **200 `status: "unavailable"`** with no file name, page, ids or text, identical in
     every case; the reason is logged content-free for operators;
   - the logged reasons are `source_not_readable`, `document_mismatch`, `rendering_changed` and
     `passage_mismatch`;
   - **`document_mismatch`** (added 2026-11-04, M10 review finding L1): the chunk lookup is keyed
     by chunk id, so the resolved chunk must also belong to the document the citation recorded, and
     the returned document must be that document. Otherwise the source is unavailable, like any
     other case.
     - The repository matches exact `(chunk_id, document_id)` pairs, so two references to the same
       chunk with different documents cannot share a result.
     - This arises only if stored references were altered, because ids are never taken from
       clients;
   - neighbours (off by default, at most two per side) come from the same readable document only,
     and only once the cited source itself is available. Their text is marker-neutralized exactly
     like the cited passage (2026-11-04, M10 review finding L3), so surrounding text cannot pose
     as a citation. Neighbours are context, not the passage the model saw, so no hash applies.
7. **Reopened conversations** list each message's citations, resolved against current access, in
   two queries per conversation; messages saved before M10.4 have `citations: []` (no backfill).
   An unavailable citation in that list has every source-describing field null, including
   `passage_truncated` (2026-11-04, M10 review finding L2), consistent with the citation endpoint's
   `UnavailableCitation`, which has no such fields at all.
8. **Evidence.** `support` is always `"not_verified"`: retrieval never proves that a source
   supports a claim (ADR 017 D-5). M10 uses **retrieval-only citations** (owner, 2026-11-05):
   claim-level verification is **deferred to a future milestone**, not part of M10, and no
   "Supported" label is introduced (ADR 019). (Until 2026-11-05 this read "claim-level checking
   is M10.7".)
9. **Out of scope.** Agent and multi-agent sources are not saved (T9 needs separate approval).

## Consequences

- The API change is additive: new optional fields (`chunk_id`, `passage_truncated`,
  `invalid_citations` on the final stream event, `message_id`, `citations` on messages) and one
  new route. Existing clients keep working.
- Changing `neutralize_markers` requires a new rendering version; citations saved under the old
  one then read as unavailable rather than showing text the model never saw.
- A user whose access was revoked still sees their old answer text (which may quote the source);
  the citation itself no longer shows anything.
- **Not yet verified against a database:** applying `0009` and the integration suite
  (`tests/integration/test_citation_isolation.py`) need the owner's approval.
