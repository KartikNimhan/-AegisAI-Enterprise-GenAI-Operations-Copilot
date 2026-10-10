/**
 * The one place every HTTP call to the AegisAI backend goes through.
 *
 * UI code (pages, components) never calls `fetch` directly — every call
 * either resolves with parsed JSON or rejects with a `BackendError`, so a
 * caller only ever has to handle one error type, never a raw network
 * exception. Mirrors frontend/streamlit/services/api/client.py's contract
 * (same error codes: timeout/network_error/malformed_response/http_error,
 * or the backend's own structured `error.code`) so both frontends treat
 * backend failures identically.
 */

import { getApiBaseUrl } from '../config'

export class BackendError extends Error {
  code: string
  statusCode?: number

  constructor(message: string, { code = 'unknown_error', statusCode }: { code?: string; statusCode?: number } = {}) {
    super(message)
    this.name = 'BackendError'
    this.code = code
    this.statusCode = statusCode
  }
}

const DEFAULT_TIMEOUT_MS = 30_000

interface RequestOptions {
  method?: string
  json?: unknown
  formData?: FormData
  params?: Record<string, string | number | undefined>
  okStatusCodes?: number[]
  signal?: AbortSignal
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(path, getApiBaseUrl())
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function parseErrorResponse(response: Response): Promise<BackendError> {
  try {
    const payload = await response.json()
    const detail = (payload && typeof payload === 'object' ? payload.error : null) ?? {}
    const message = detail.message || `The backend returned HTTP ${response.status}`
    const code = detail.code || 'http_error'
    return new BackendError(message, { code, statusCode: response.status })
  } catch {
    return new BackendError(`The backend returned HTTP ${response.status}`, {
      code: 'http_error',
      statusCode: response.status,
    })
  }
}

export async function requestJson<T = unknown>(path: string, options: RequestOptions = {}): Promise<T | null> {
  const { method = 'GET', json, formData, params, okStatusCodes, signal } = options
  const url = buildUrl(path, params)

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS)
  if (signal) {
    signal.addEventListener('abort', () => controller.abort())
  }

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: formData ?? (json !== undefined ? JSON.stringify(json) : undefined),
      signal: controller.signal,
    })
  } catch (exc) {
    if (controller.signal.aborted && !signal?.aborted) {
      throw new BackendError('The backend did not respond in time. Please try again.', { code: 'timeout' })
    }
    if (signal?.aborted) {
      throw exc
    }
    throw new BackendError('Could not reach the backend. Check that it is running.', { code: 'network_error' })
  } finally {
    clearTimeout(timeoutId)
  }

  const allowed = okStatusCodes ?? Array.from({ length: 100 }, (_, i) => 200 + i)
  if (!allowed.includes(response.status)) {
    throw await parseErrorResponse(response)
  }

  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null

  try {
    return JSON.parse(text) as T
  } catch {
    throw new BackendError('The backend returned an unexpected response.', { code: 'malformed_response' })
  }
}
