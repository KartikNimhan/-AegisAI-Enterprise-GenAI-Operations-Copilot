/**
 * Strict loaders for the Overview (M10 review finding M2).
 *
 * The general API wrappers turn an empty 2xx body into zeros or empty lists (for example
 * `getOperationsSummary` returns `{ total_documents: 0 }` for a 204). That is convenient elsewhere
 * but wrong on a page whose job is to report what the backend holds: missing data must never read
 * as "0" (M10 decision 11). These loaders accept only a well-formed body and otherwise throw
 * `MalformedDataError`; a failed request still throws the usual `BackendError`. So the Overview
 * can tell three cases apart:
 * - unavailable: the request failed (HTTP error, network, timeout);
 * - malformed: a 2xx answer with no body (204, empty 200), a body that is not JSON, or one of the
 *   wrong shape (`{}`);
 * - empty: a well-formed answer that really holds nothing (shown as 0 / "No conversations yet").
 */

import { BackendError, requestJson } from './client'
import type { ConversationSummary } from './conversations'
import type { OperationsSummary } from './operations'
import type { SystemStatus } from './system'

export class MalformedDataError extends Error {
  constructor(what: string) {
    super(`The backend returned ${what} in an unexpected form.`)
    this.name = 'MalformedDataError'
  }
}

/** The JSON body of a successful answer. A 2xx whose body is not JSON is unusable data, not a
 * failed request (M10 review follow-up F1): `requestJson` reports it as `malformed_response`,
 * which is turned into `MalformedDataError` here. Every other error (HTTP status, network,
 * timeout) passes through unchanged. */
async function successfulBody(path: string, what: string): Promise<unknown> {
  try {
    return await requestJson<unknown>(path)
  } catch (error) {
    if (error instanceof BackendError && error.code === 'malformed_response') {
      throw new MalformedDataError(what)
    }
    throw error
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

export async function loadOperationsSummary(): Promise<OperationsSummary> {
  const payload = await successfulBody('/api/v1/operations/summary', 'the document summary')
  if (
    !isRecord(payload) ||
    !isCount(payload.total_documents) ||
    !isRecord(payload.documents_by_status) ||
    !Object.values(payload.documents_by_status).every(isCount)
  ) {
    throw new MalformedDataError('the document summary')
  }
  return payload as unknown as OperationsSummary
}

export async function loadConversations(): Promise<ConversationSummary[]> {
  const payload = await successfulBody('/api/v1/conversations', 'the conversation list')
  if (
    !Array.isArray(payload) ||
    !payload.every(
      (item) =>
        isRecord(item) &&
        typeof item.id === 'string' &&
        typeof item.updated_at === 'string' &&
        (item.title === null || typeof item.title === 'string'),
    )
  ) {
    throw new MalformedDataError('the conversation list')
  }
  return payload as ConversationSummary[]
}

export async function loadMemoryCount(): Promise<number> {
  const payload = await successfulBody('/api/v1/memories', 'the memory list')
  if (!Array.isArray(payload) || !payload.every((item) => isRecord(item) && typeof item.id === 'string')) {
    throw new MalformedDataError('the memory list')
  }
  return payload.length
}

export async function loadSystemStatus(): Promise<SystemStatus> {
  const payload = await successfulBody('/api/v1/system/status', 'the system status')
  if (!isRecord(payload) || typeof payload.database !== 'string' || typeof payload.redis !== 'string') {
    throw new MalformedDataError('the system status')
  }
  return payload as unknown as SystemStatus
}
