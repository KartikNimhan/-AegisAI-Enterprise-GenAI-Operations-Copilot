/**
 * Streaming over Server-Sent Events: `POST /api/v1/rag/chat/stream`,
 * `POST /api/v1/chat/completions/stream` and `POST /api/v1/agents/run/stream`.
 *
 * The browser's `EventSource` can only GET and cannot send an Authorization header, so the
 * stream is read from a `fetch` response body instead. Frames are `data: <json>\n\n` (the agent
 * stream also names each frame with an `event:` line). The chat streams end with `data: [DONE]`,
 * or with a terminal `{"error": {...}}` frame when the model fails mid-answer (the HTTP status is
 * already 200 by then); the agent stream ends with a `completed` event, or an `error` event.
 *
 * Failure contract: each promise resolves only when the server said it was done. Every other
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

interface SseFrame {
  event: string
  data: string
}

function parseFrame(frame: string): SseFrame | null {
  // A frame is one or more lines; `data:` lines carry the payload (joined with newlines per the
  // SSE spec) and an optional `event:` line names it. Everything else is ignored.
  const lines = frame.split(/\r?\n/)
  const data = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
  if (!data.length) return null
  const eventLine = lines.find((line) => line.startsWith('event:'))
  return { event: eventLine ? eventLine.slice(6).trim() : 'message', data: data.join('\n') }
}

function malformed(): BackendError {
  return new BackendError('The backend returned an unexpected response.', {
    code: 'malformed_response',
  })
}

async function openStream(
  path: string,
  payload: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<Response> {
  let response: Response
  try {
    response = await fetch(buildUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify(payload),
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
  if (!response.body) throw malformed()
  return response
}

/** Reads frames until `handle` returns true (the server said it is done). Rejects if the stream
 * ends first. */
async function consumeFrames(
  response: Response,
  signal: AbortSignal | undefined,
  handle: (frame: SseFrame) => boolean,
): Promise<void> {
  const reader = (response.body as ReadableStream<Uint8Array>).getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done = false

  function handleRaw(raw: string) {
    const frame = parseFrame(raw)
    if (frame && handle(frame)) done = true
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
      for (const raw of frames) {
        handleRaw(raw)
        if (done) break
      }
    }
    if (!done && buffer.trim()) handleRaw(buffer)
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

function parseJson(data: string): Record<string, unknown> {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    throw malformed()
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw malformed()
  return parsed as Record<string, unknown>
}

function throwIfError(body: Record<string, unknown>) {
  const error = body.error as { code?: string; message?: string } | undefined
  if (error) {
    throw new BackendError(error.message || 'The answer could not be completed.', {
      code: error.code || 'stream_error',
    })
  }
}

async function streamConversation(
  path: string,
  { message, conversationId, signal, onChunk }: StreamRequest,
): Promise<void> {
  const response = await openStream(
    path,
    { message, ...(conversationId ? { conversation_id: conversationId } : {}) },
    signal,
  )
  await consumeFrames(response, signal, (frame) => {
    if (frame.data === '[DONE]') return true
    const body = parseJson(frame.data) as { error?: unknown } & Partial<StreamChunk>
    throwIfError(body as Record<string, unknown>)
    onChunk({
      conversation_id: body.conversation_id ?? '',
      delta: body.delta ?? '',
      is_final: Boolean(body.is_final),
      sources: body.sources ?? null,
    })
    return false
  })
}

/** `POST /api/v1/rag/chat/stream`: an answer grounded in the user's documents, with sources. */
export function streamRagChat(request: StreamRequest): Promise<void> {
  return streamConversation('/api/v1/rag/chat/stream', request)
}

/** `POST /api/v1/chat/completions/stream`: plain chat with the model (no documents). */
export function streamPlainChat(request: StreamRequest): Promise<void> {
  return streamConversation('/api/v1/chat/completions/stream', request)
}

export type AgentStreamEvent =
  | { type: 'tool_started'; toolName: string }
  | { type: 'tool_completed'; toolName: string; success: boolean }
  | { type: 'answer_delta'; delta: string }
  | { type: 'completed'; status: string; conversationId: string | null }

export interface AgentStreamRequest {
  message: string
  conversationId?: string | null
  signal?: AbortSignal
  onEvent: (event: AgentStreamEvent) => void
}

/** `POST /api/v1/agents/run/stream`: tool steps as they happen, then the answer. */
export async function streamAgentRun({
  message,
  conversationId,
  signal,
  onEvent,
}: AgentStreamRequest): Promise<void> {
  const response = await openStream(
    '/api/v1/agents/run/stream',
    { message, ...(conversationId ? { conversation_id: conversationId } : {}) },
    signal,
  )
  await consumeFrames(response, signal, (frame) => {
    const body = parseJson(frame.data)
    if (frame.event === 'error') throwIfError(body)
    switch (frame.event) {
      case 'tool_started':
        onEvent({ type: 'tool_started', toolName: String(body.tool_name ?? 'unknown') })
        return false
      case 'tool_completed':
        onEvent({
          type: 'tool_completed',
          toolName: String(body.tool_name ?? 'unknown'),
          success: Boolean(body.success),
        })
        return false
      case 'answer_delta':
        onEvent({ type: 'answer_delta', delta: String(body.delta ?? '') })
        return false
      case 'completed':
        onEvent({
          type: 'completed',
          status: String(body.status ?? 'completed'),
          conversationId: typeof body.conversation_id === 'string' ? body.conversation_id : null,
        })
        return true
      default:
        return false // an event this client does not know is ignored, not fatal
    }
  })
}
