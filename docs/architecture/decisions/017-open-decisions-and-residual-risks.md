# 17. Open Decisions and Residual Risks (M0–M8)

## Status

Proposed — 2026-10-22. Nothing here is decided. These items came out of the M0–M8 gap analysis and
each needs a product or architecture decision, a database, a live provider or an operator before it
can honestly be called done. This file exists so none of them is mistaken for finished work.

## Decisions needed

| # | Question | Options | Risk of waiting | Recommendation |
|---|---|---|---|---|
| D-1 | Activate the configured `safety` model role? | (a) leave unused; (b) classify user input before the main call; (c) classify model output before it is returned | The role is configured and routed (`ModelRole.SAFETY`) but nothing calls it, so no guardrail exists. This is a M9 (Responsible AI) feature, not an M1 gap | (b) behind a setting, off by default, with a fixed refusal message and a metric. Decide the policy (what is refused) first |
| D-2 | Human approval for sensitive tools (`ToolDefinition.requires_approval`)? | (a) keep the field unused; (b) pause the graph and ask the user | Every current tool is read-only, so there is no exposure today. The first write-capable tool makes this urgent | (a) until a write tool is proposed; make "no write tool without approval" a review rule |
| D-3 | Move document processing to background workers? | (a) keep it synchronous in the request; (b) a queue and worker (`app/workers/` is empty) | Large documents hold a request open and an embedding job holds a model in the API process. Bounded now by the upload, extraction and rate limits | (b) when real documents get large. It adds a service (queue) and a status-polling UI |
| D-4 | Add an approximate-nearest-neighbour index (HNSW/IVFFlat)? | (a) exact scan (current, ADR 006); (b) HNSW | Exact search is correct and slows with the corpus. ADR 006 recorded this as a deliberate choice | (a) until measured latency says otherwise. Then add HNSW in a migration after measuring recall on this corpus |
| D-5 | Check that a cited source actually supports the claim? | (a) retrieval check only (current); (b) an LLM or NLI check | Today `[S2]` only proves S2 was retrieved. A model can cite a real source for an unsupported claim | (a), stated plainly in docs and UI. (b) costs a model call per answer and needs an evaluation set first |
| D-6 | Unique index on `(owner, checksum)`? | see ADR 016 "Not done" | Concurrent identical uploads are narrowed by an advisory lock but not forbidden by the database | Operator de-duplication, then a migration. Needs a real database |
| D-7 | Hard database cap on memories per user? | counter column, trigger, or keep the row lock | The cap holds only while every writer uses the service | Keep the row lock; revisit if another writer appears |
| D-8 | How to version embeddings? | see below | A changed model with an unchanged version label silently mixes vectors | Policy below |
| D-9 | When should the security scans block a merge? | (a) reporting only (current, `security.yml`); (b) block on new Critical/High findings; (c) block on any finding | A known-vulnerable dependency or a leaked secret can be merged while every check is green | (b), once the baseline review is finished (partly done, see `docs/operations/security-scanning.md`; the artifacts need a signed-in GitHub account). Gitleaks findings should block as soon as the baseline is clean |
| D-10 | Token or cost budgets per user? | (a) request-count rate limits only (current); (b) a daily token budget per user; (c) per-organization quotas | Rate limits bound requests, not tokens: long prompts within the limits still cost more | (a) for a single team; (b) before any shared or paid deployment, using the token counts already stored per message |
| D-11 | Harden the bundled PostgreSQL and Redis manifests? | (a) leave as development/staging-only examples (current); (b) add non-root security contexts | Those two pods run with the images' defaults (PostgreSQL's entrypoint starts as root to drop to `postgres`) | (a), and use a managed database in production, as `infra/kubernetes/README.md` already recommends |
| D-12 | Keep the legacy Streamlit UI? | (a) keep as a tested legacy UI; (b) remove it | It cannot call an authentication-enabled backend (no sign-in), and it renders model answers as Markdown, so an injected Markdown image would be fetched by the browser if it were ever used against such a backend | (b) eventually; until then it is documented as unsupported with authentication |

## Embedding versioning policy (D-8)

`EMBEDDING_MODEL_VERSION` is a label an operator sets; the application cannot read the weights'
identity from a Sentence Transformers model name, and does not claim to. Policy:

1. Bump `EMBEDDING_MODEL_VERSION` whenever anything that changes the vectors changes: the model
   name, its revision (if you pin one), normalization (`EMBEDDING_NORMALIZE`), or pooling code.
2. Vectors are keyed by model name plus version, so a bump re-embeds on the next
   `POST /documents/{id}/embeddings` and retrieval only ever compares vectors of one model/version.
3. A model with a different dimension needs a new migration first. The API refuses to start with a
   dimension that does not match the column.
4. Pinning a model revision (a commit hash) would make the version verifiable. It is a change to
   the provider and the model download, so it is listed here, not done.

## Citation scope (D-5, stated for readers of the API)

The `cited` flag and `invalid_citations` list answer one question: *was this source id among the
chunks retrieved for this question?* They do not say the cited chunk supports the sentence it
follows. Do not describe this as fact checking.

## Residual risks that need an environment

- Everything that touches PostgreSQL (migrations, pgvector search, cross-user isolation, the
  advisory and row locks) is covered by offline tests and, in CI, by the integration suite against a
  throwaway PostgreSQL service (the `test` job, green on `4f151d2`; its log has not been read). It
  has not run against a deployed database.
- Live Groq behaviour beyond one completion and one stream, which both passed locally on 2026-10-25
  (reported by the maintainer), and one live RAG answer, which passed in CI (`rag-e2e-live.yml`
  run #3 on `f164c04`): retries, `Retry-After`, the stream deadline and tool calling.
- Identity-provider login and token validation; the web UI in a real browser.
- A real Prometheus scrape; the Kubernetes secret flow.
- The extraction limits and body limits are generous starting points, not tuned values.
