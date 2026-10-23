/**
 * The preview's entire backend: a `fetch` and `XMLHttpRequest` replacement that answers from
 * `mockData.ts` and NEVER touches the network.
 *
 * Chat answers are canned text chosen by keywords in the question (`mockAnswerFor`), always
 * labelled "[MOCK ANSWER]", and streamed one word at a time so the UI behaves as it would with a
 * real model. The question is read only to pick that text; it is not stored or sent anywhere.
 *
 * Safety properties (all covered by tests):
 * - nothing reaches the real `fetch`: an unknown URL gets a 404 "not part of the preview";
 * - no request is sent with credentials: the mock ignores headers entirely;
 * - every change (POST/PATCH/DELETE other than the canned chat streams) is refused with a
 *   clear "preview is read-only" error, so nothing appears to be saved.
 */

import {
  MOCK_CHUNKS,
  MOCK_CONVERSATIONS,
  MOCK_CONVERSATION_MESSAGES,
  MOCK_DOCUMENTS,
  MOCK_EMBEDDING_STATUS,
  MOCK_MEMORIES,
  MOCK_OPERATIONS,
  MOCK_SYSTEM_STATUS,
  MOCK_WORKFLOW_AGENTS,
  mockAnswerFor,
} from './mockData'

/** Pause between streamed frames, so an answer visibly arrives word by word. */
export const DEFAULT_CHUNK_DELAY_MS = 40

export interface MockReply {
  status: number
  /** JSON body (ignored when `sse` is set). */
  body?: unknown
  /** A canned server-sent-events body, one entry per frame (sent one at a time). */
  sse?: string[]
  /** The request never gets an answer (see `/health`). */
  pending?: true
}

const READ_ONLY_ERROR = {
  error: {
    code: 'preview_read_only',
    message: 'Preview mode: this is mock data, so changes are not saved.',
  },
}

const NOT_IN_PREVIEW = {
  error: { code: 'not_in_preview', message: 'Preview mode: this request is not part of the preview.' },
}

function frame(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`
}

function namedFrame(event: string, payload: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`
}

const CONVERSATION_ID = 'preview-conversation'

function words(text: string): string[] {
  return text.split(' ').map((word, index) => (index === 0 ? word : ` ${word}`))
}

function chatStream(question: string, rag: boolean): string[] {
  const answer = mockAnswerFor(question)
  // Plain chat does not search documents, so it neither cites nor lists sources.
  const text = rag ? answer.text : answer.text.replace(/\s*\[S\d+\]/g, '')
  const frames = words(text).map((delta) =>
    frame({ conversation_id: CONVERSATION_ID, delta, is_final: false, sources: null }),
  )
  frames.push(
    frame({
      conversation_id: CONVERSATION_ID,
      delta: '',
      is_final: true,
      sources: rag ? answer.sources : null,
    }),
  )
  frames.push('data: [DONE]\n\n')
  return frames
}

function agentStream(question: string): string[] {
  const answer = mockAnswerFor(question)
  return [
    namedFrame('tool_started', { tool_name: answer.tool }),
    namedFrame('tool_completed', { tool_name: answer.tool, success: true }),
    ...words(answer.text).map((delta) => namedFrame('answer_delta', { delta })),
    namedFrame('completed', { status: 'completed', conversation_id: CONVERSATION_ID }),
  ]
}

function workflow(question: string) {
  return {
    workflow_id: 'preview-workflow',
    correlation_id: 'preview-correlation',
    status: 'completed',
    answer: mockAnswerFor(question).text,
    agents_used: MOCK_WORKFLOW_AGENTS,
    sources: [],
    token_usage: {},
    duration_ms: 150,
  }
}

/** The pure routing table: method + path (+ the chat question) in, canned reply out. No I/O. */
export function previewReply(method: string, rawUrl: string, question = ''): MockReply {
  let path: string
  try {
    path = new URL(rawUrl, 'http://preview.invalid').pathname
  } catch {
    return { status: 404, body: NOT_IN_PREVIEW }
  }
  const verb = method.toUpperCase()

  if (verb === 'POST') {
    if (path === '/api/v1/rag/chat/stream') return { status: 200, sse: chatStream(question, true) }
    if (path === '/api/v1/chat/completions/stream') {
      return { status: 200, sse: chatStream(question, false) }
    }
    if (path === '/api/v1/agents/run/stream') return { status: 200, sse: agentStream(question) }
    if (path === '/api/v1/multi-agent/run') return { status: 200, body: workflow(question) }
  }

  if (verb !== 'GET') {
    return path.startsWith('/api/v1/') ? { status: 409, body: READ_ONLY_ERROR } : { status: 404, body: NOT_IN_PREVIEW }
  }

  // The top bar polls /health to say "Backend connected". There is no backend to ask, so this is
  // never answered: the bar stays on "Connecting…" instead of claiming a connection (or, after a
  // timeout, claiming the backend is unreachable, which was not checked either).
  if (path === '/health') return { status: 200, pending: true }
  if (path === '/api/v1/documents') {
    return { status: 200, body: { items: MOCK_DOCUMENTS, total: MOCK_DOCUMENTS.length } }
  }
  if (/^\/api\/v1\/documents\/[^/]+\/chunks$/.test(path)) {
    return { status: 200, body: { items: MOCK_CHUNKS, total: MOCK_CHUNKS.length } }
  }
  if (/^\/api\/v1\/documents\/[^/]+\/embeddings$/.test(path)) {
    return { status: 200, body: MOCK_EMBEDDING_STATUS }
  }
  if (path === '/api/v1/operations/summary') return { status: 200, body: MOCK_OPERATIONS }
  if (path === '/api/v1/system/status') return { status: 200, body: MOCK_SYSTEM_STATUS }
  if (path === '/api/v1/conversations') return { status: 200, body: MOCK_CONVERSATIONS }
  const conversation = /^\/api\/v1\/conversations\/([^/]+)$/.exec(path)
  if (conversation) {
    const found = MOCK_CONVERSATIONS.find((item) => item.id === conversation[1])
    return found
      ? { status: 200, body: { ...found, messages: MOCK_CONVERSATION_MESSAGES } }
      : { status: 404, body: { error: { code: 'not_found', message: 'Conversation not found' } } }
  }
  if (path === '/api/v1/memories') return { status: 200, body: MOCK_MEMORIES }

  return { status: 404, body: NOT_IN_PREVIEW }
}

const encoder = new TextEncoder()

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError')
}

/** Sends `frames` one at a time, `delayMs` apart. Aborting the request stops the stream with an
 * AbortError, as a real fetch does, so "Stop generating" works. */
function streamFrames(frames: string[], delayMs: number, signal?: AbortSignal | null) {
  let timer: ReturnType<typeof setTimeout> | undefined
  return new ReadableStream<Uint8Array>({
    start(controller) {
      let index = 0
      const stop = () => {
        clearTimeout(timer)
        try {
          controller.error(abortError())
        } catch {
          /* already closed */
        }
      }
      if (signal?.aborted) return stop()
      signal?.addEventListener('abort', stop, { once: true })
      const next = () => {
        if (index >= frames.length) {
          signal?.removeEventListener('abort', stop)
          controller.close()
          return
        }
        controller.enqueue(encoder.encode(frames[index]))
        index += 1
        timer = setTimeout(next, delayMs)
      }
      next()
    },
    cancel() {
      clearTimeout(timer)
    },
  })
}

function toResponse(reply: MockReply, delayMs: number, signal?: AbortSignal | null): Response {
  if (reply.sse !== undefined) {
    return new Response(streamFrames(reply.sse, delayMs, signal), {
      status: reply.status,
      headers: { 'Content-Type': 'text/event-stream' },
    })
  }
  return new Response(reply.status === 204 ? null : JSON.stringify(reply.body ?? null), {
    status: reply.status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A stand-in for `XMLHttpRequest`, used only by the document upload (it wants progress events).
 * It never opens a connection: every upload is refused as read-only. */
class PreviewXhr {
  status = 0
  responseText = ''
  timeout = 0
  upload: { onprogress: ((event: unknown) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  ontimeout: (() => void) | null = null

  open(): void {}
  setRequestHeader(): void {}
  send(): void {
    queueMicrotask(() => {
      this.status = 409
      this.responseText = JSON.stringify(READ_ONLY_ERROR)
      this.onload?.()
    })
  }
}

export interface PreviewTarget {
  fetch: typeof fetch
  XMLHttpRequest: typeof XMLHttpRequest
}

/** The chat question from a JSON request body; anything else is ignored. */
function questionFrom(body: BodyInit | null | undefined): string {
  if (typeof body !== 'string') return ''
  try {
    const parsed: unknown = JSON.parse(body)
    const message = (parsed as { message?: unknown } | null)?.message
    return typeof message === 'string' ? message : ''
  } catch {
    return ''
  }
}

/** Replaces `fetch` and `XMLHttpRequest` on `target`. Returns a function that restores them. */
export function installPreviewApi(
  target: PreviewTarget,
  { chunkDelayMs = DEFAULT_CHUNK_DELAY_MS }: { chunkDelayMs?: number } = {},
): () => void {
  const originalFetch = target.fetch
  const originalXhr = target.XMLHttpRequest

  target.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
    const method = init?.method ?? (typeof input === 'object' && 'method' in input ? input.method : 'GET')
    const reply = previewReply(method, url, questionFrom(init?.body))
    // Deliberately never settles, not even on abort: a timeout would turn into a false
    // "Backend unreachable". One idle promise per poll is harmless.
    if (reply.pending) return new Promise<Response>(() => undefined)
    return toResponse(reply, chunkDelayMs, init?.signal)
  }) as typeof fetch
  target.XMLHttpRequest = PreviewXhr as unknown as typeof XMLHttpRequest

  return () => {
    target.fetch = originalFetch
    target.XMLHttpRequest = originalXhr
  }
}
