/**
 * Streaming chat over Server-Sent Events: `POST /api/v1/rag/chat/stream`.
 *
 * The browser's `EventSource` can only GET and cannot send an Authorization header, so the
 * stream is read from a `fetch` response body instead. Frames are `data: <json>\n\n`; the
 * stream ends with `data: [DONE]`, or with a terminal `{"error": {...}}` frame when the model
 * fails mid-answer (the HTTP status is already 200 by then).
 *
 * Failure contract: this promise resolves only when the server said it was done. Every other
 * ending rejects with a `BackendError` (`stream_interrupted` when the connection closed early),
 * and an abort via `signal` rejects with the original `AbortError` so the caller can tell a
 * user-initiated stop from a failure. There is deliberately NO automatic reconnect: the request
 * is a POST that creates a conversation turn and spends model tokens, and the server rolls an
 * interrupted turn back, so retrying is an explicit user action that sends the message again.
 */

import { authHeaders, notifyUnauthorized } from '../auth/token'
import { BackendError, buildUrl, parseErrorResponse } from './client'

export interface StreamSource {
  source_id: string
  document_id: string
  filename: string
  chunk_index: number
  page: number | null
  similarity: number
  cited: boolean
}

export interface StreamChunk {
  conversation_id: string
  delta: string
  is_final: boolean
  sources: StreamSource[] | null
}

export interface StreamRequest {
  message: string
  conversationId?: string | null
  signal?: AbortSignal
  onChunk: (chunk: StreamChunk) => void
}

function parseFrame(frame: string): string | null {
  // A frame is one or more lines; only `data:` lines carry payload (`event:` is used by the
  // agent stream, not this one). Multiple data lines are joined with newlines per the SSE spec.
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
  return data.length ? data.join('\n') : null
}

export async function streamRagChat({
  message,
  conversationId,
  signal,
  onChunk,
}: StreamRequest): Promise<void> {
  let response: Response
  try {
    response = await fetch(buildUrl('/api/v1/rag/chat/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify({ message, ...(conversationId ? { conversation_id: conversationId } : {}) }),
      signal,
    })
  } catch (exc) {
    if (signal?.aborted) throw exc
    throw new BackendError('Could not reach the backend. Check that it is running.', {
      code: 'network_error',
    })
  }

  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await parseErrorResponse(response)
  }
  if (!response.body) {
    throw new BackendError('The backend returned an unexpected response.', {
      code: 'malformed_response',
    })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done = false

  function handle(frame: string) {
    const payload = parseFrame(frame)
    if (payload === null) return
    if (payload === '[DONE]') {
      done = true
      return
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(payload)
    } catch {
      throw new BackendError('The backend returned an unexpected response.', {
        code: 'malformed_response',
      })
    }
    const body = parsed as { error?: { code?: string; message?: string } } & Partial<StreamChunk>
    if (body.error) {
      throw new BackendError(body.error.message || 'The answer could not be completed.', {
        code: body.error.code || 'stream_error',
      })
    }
    onChunk({
      conversation_id: body.conversation_id ?? '',
      delta: body.delta ?? '',
      is_final: Boolean(body.is_final),
      sources: body.sources ?? null,
    })
  }

  try {
    while (!done) {
      let result: ReadableStreamReadResult<Uint8Array>
      try {
        result = await reader.read()
      } catch (exc) {
        if (signal?.aborted) throw exc
        throw new BackendError('The connection was lost before the answer finished.', {
          code: 'stream_interrupted',
        })
      }
      if (result.done) break
      buffer += decoder.decode(result.value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        handle(frame)
        if (done) break
      }
    }
    if (!done && buffer.trim()) handle(buffer)
  } finally {
    // Stop the download if we leave early (abort, error, or done); ignore errors from a dead socket.
    reader.cancel().catch(() => undefined)
  }

  if (!done) {
    throw new BackendError('The connection closed before the answer finished.', {
      code: 'stream_interrupted',
    })
  }
}
