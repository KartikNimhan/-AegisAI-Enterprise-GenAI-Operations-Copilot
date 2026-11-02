import { vi } from 'vitest'

const encoder = new TextEncoder()

export interface ControlledStream {
  /** Sends raw bytes (as text) to the reader, exactly as given: frames may be split anywhere. */
  push: (text: string) => void
  /** A well-formed data frame. */
  frame: (payload: unknown) => void
  /** A named frame (`event: <name>`), as the agent stream sends. */
  event: (name: string, payload: unknown) => void
  done: () => void
  /** Ends the body without `[DONE]` (a dropped connection that closes cleanly). */
  close: () => void
  /** Breaks the body with a network error. */
  break: () => void
}

/** Installs a fetch mock whose streaming endpoint is driven by the test. `/health` answers ok.
 * Other URLs get `others(url, init)`. Aborting the request signal errors the body with an
 * AbortError, like a real fetch does. */
export function installStreamingFetch(
  options: {
    /** The streaming endpoint this mock serves (default: the RAG stream). */
    path?: string
    status?: number
    errorBody?: unknown
    others?: (url: string, init?: RequestInit) => { status: number; body: unknown }
  } = {},
) {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const requests: { url: string; body: unknown; headers: Record<string, string> }[] = []

  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes(options.path ?? '/api/v1/rag/chat/stream')) {
      requests.push({
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        headers: (init?.headers ?? {}) as Record<string, string>,
      })
      const status = options.status ?? 200
      if (status !== 200) {
        return {
          status,
          ok: false,
          json: async () => options.errorBody ?? {},
          text: async () => JSON.stringify(options.errorBody ?? {}),
        } as unknown as Response
      }
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          controller = c
          init?.signal?.addEventListener('abort', () => {
            try {
              c.error(new DOMException('The operation was aborted.', 'AbortError'))
            } catch {
              /* already closed */
            }
          })
        },
      })
      return { status: 200, ok: true, body } as unknown as Response
    }
    const other =
      url.includes('/health') && !url.includes('/health/ready')
        ? { status: 200, body: { status: 'ok' } }
        : (options.others?.(url, init) ?? { status: 200, body: {} })
    return {
      status: other.status,
      ok: other.status < 300,
      text: async () => JSON.stringify(other.body),
      json: async () => other.body,
    } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)

  const stream: ControlledStream = {
    push: (text) => controller.enqueue(encoder.encode(text)),
    frame: (payload) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)),
    event: (name, payload) =>
      controller.enqueue(encoder.encode(`event: ${name}
data: ${JSON.stringify(payload)}

`)),
    done: () => {
      controller.enqueue(encoder.encode('data: [DONE]\n\n'))
      controller.close()
    },
    close: () => controller.close(),
    break: () => controller.error(new TypeError('network error')),
  }
  return { stream, requests, fetchMock }
}

export function chunk(delta: string, extra: Record<string, unknown> = {}) {
  return { conversation_id: 'conv-1', delta, is_final: false, sources: null, ...extra }
}
