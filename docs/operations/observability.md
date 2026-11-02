# Observability: metrics

**Status: implemented and unit-tested; never scraped by a real Prometheus and never deployed.** This
page describes the opt-in metrics endpoint. Logs (structured JSON with a request id) and the
`/health` and `/health/ready` probes are described in the README and
[production-readiness.md](production-readiness.md). **Not implemented:** tracing, dashboards, alert
rules, and metrics for the database, embeddings, uploads or agents.

## Turning it on

Metrics are **off by default**. Until they are enabled nothing is recorded and `GET /metrics` does
not exist (it answers 404).

| Setting | Default | Meaning |
|---|---|---|
| `METRICS_ENABLED` | `false` | `true` starts recording and mounts `GET /metrics` |
| `METRICS_TOKEN` | unset | The bearer token a scraper must send. At least 16 characters, with no leading, trailing or only-whitespace content (a newline copied from a secret file is rejected at startup rather than causing silent 401s). **Required outside local development**: the API refuses to start with metrics enabled and no token. Keep it out of version control. Generate a random value with, for example, `openssl rand -hex 32` or `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

In local development, enabling metrics without a token still mounts the route, but it answers 401 to
every request (it fails closed) and a startup message says so.

Kubernetes: `METRICS_ENABLED` is in `infra/kubernetes/backend-configmap.yaml` (`"false"`). To
enable, set it to `"true"` and add `METRICS_TOKEN` to the backend Secret you create yourself (never
to the ConfigMap or an example file). Compose passes both variables through from your environment.

## The endpoint

`GET /metrics` returns the Prometheus text format and needs `Authorization: Bearer <METRICS_TOKEN>`:

- It is mounted at the application root like `/health`, **outside** the OIDC-protected API: scrapers
  do not do OIDC. It has its own guard, a static token compared in constant time. A missing, wrong or
  malformed token is a generic 401 (no hint which part failed); the token is never logged or returned. The guard reads the settings of the application instance it is mounted on. Brute-force guessing is not rate limited here; the 16-character minimum and a network policy limiting who can reach the endpoint are the defence.
- It is not in the OpenAPI schema, and the frontend's nginx proxies only `/api/` and `/health`, so it
  is not reachable through the frontend. The backend port itself is published by Compose; the
  Kubernetes Service is `ClusterIP`. There is no NetworkPolicy in the repository, so anything that can
  reach the backend Service can try the endpoint (it still needs the token).
- Only this application's series are exposed (a dedicated registry). The default `process_*` and
  `python_*` collectors, which expose memory, file descriptors and interpreter details, are not used.

## Series

| Series | Labels | Notes |
|---|---|---|
| `aegis_http_requests_total` | `method`, `route`, `status` | route is the matched route template, e.g. `/api/v1/documents/{document_id}/chunks`; a request that matched no route is `unmatched`; scrapes of `/metrics` are not counted |
| `aegis_http_request_duration_seconds` | `method`, `route` | **Time until the response started (headers ready), not the total duration of a streamed (SSE) response.** For streaming endpoints this is time to first byte |
| `aegis_rate_limit_refusals_total` | `bucket` | requests refused with 429 (`llm`, `upload`, `embedding`) |
| `aegis_rate_limiter_unavailable_total` | `bucket` | requests refused with 503 because the limiter itself failed |
| `aegis_llm_requests_total` | `provider`, `model_role`, `operation`, `outcome` | one per gateway call, by final outcome (`success` or `error`); `operation` is `chat_completion` or `stream_chat_completion` |
| `aegis_llm_errors_total` | `provider`, `error_type` | failed calls by LLM error class; an unknown class is `other` |
| `aegis_llm_retries_total` | `provider`, `error_type` | retries after a retryable error (streams are never retried) |
| `aegis_llm_request_duration_seconds` | `provider`, `operation` | one observation per provider attempt; for streams, the whole stream |
| `aegis_llm_tokens_total` | `provider`, `model_role`, `direction` | tokens the provider reported, `input` or `output`. A call whose usage was not reported adds nothing, so this can undercount |

Status codes in `aegis_http_requests_total` include 500 for unhandled exceptions: the middleware
counts them and re-raises, so the existing error handling is unchanged. The status is the one the
middleware sees; a streaming response that fails after its 200 headers were sent is counted as 200.
CORS preflight (`OPTIONS`) requests are answered by the CORS middleware before this one and are
not counted.

## Privacy and cardinality controls

- Labels come from fixed vocabularies (`model_role`, `operation`, `outcome` and `direction` are closed sets; any other value becomes `other`) or, for `provider`, are sanitised to a short lower-case token (otherwise
  `other`). They never contain user, organization, conversation, document or request ids, e-mail
  addresses, file names, query strings, model output, prompts or error messages.
- Routes are templates, so any number of ids produce one series. Unknown HTTP methods collapse to
  `OTHER`. `model_role` (`primary`, `fast`, `safety`) is used instead of model names.
- Unit tests check these rules: the label-name allowlist, hostile label values, and that after
  authenticated, unauthenticated, failing and rate-limited traffic the output contains no principal
  e-mail, user or organization id, bearer token, request id, path id, query string or error text.
- The aggregate series still reveal usage patterns (routes, error rates, token volumes), which is
  why the endpoint is off by default and token-protected.

## Limitations

- **Per process.** Counters live in the memory of one process (the backend runs a single uvicorn
  process). They reset on restart, and with several workers each would report its own counts.
- **Recording is best effort**, including route-template resolution. A non-`LLMError` exception raised by a provider is counted once with error type `other` and then re-raised unchanged.
- **Recording is best effort (details).** A failure while recording is swallowed (and logged at debug level) so
  metrics can never change a response. A rare failure therefore loses a data point silently.
- **Streams that are abandoned** (the client disconnects mid-stream) record no outcome for that
  stream.
- **Not verified:** a real Prometheus scrape, scrape configuration, dashboards or alerts, behaviour
  under load or with several workers.

## Verification

Offline unit tests in `backend/tests/unit/observability/` cover: off by default, the endpoint
(absent when disabled; missing, wrong and malformed tokens; correct token; independence from OIDC;
no token in logs), settings validation, route-template cardinality including the router prefix,
404 and 500 handling, rate-limit refusals and limiter failures, LLM successes, errors, retries,
missing usage and streaming usage, and the privacy checks above. They use a fresh registry per test
and the scripted LLM provider, with no Docker, network or database.

## Suggested first alerts (not implemented)

Rates of `aegis_http_requests_total{status=~"5.."}`, `aegis_rate_limit_refusals_total`,
`aegis_rate_limiter_unavailable_total` and `aegis_llm_errors_total`, plus a scrape-down alert. Define
thresholds from observed traffic; none are proposed here.
