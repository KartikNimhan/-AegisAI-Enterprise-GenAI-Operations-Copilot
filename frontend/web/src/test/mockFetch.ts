import { vi } from 'vitest'

type Responder = (url: string, init?: RequestInit) => { status: number; body: unknown } | Promise<{ status: number; body: unknown }>

/** Installs a `global.fetch` mock keyed by a simple path-matching
 * responder, and always answers `/health` with 200 ok so the
 * always-mounted Topbar's polling doesn't interfere with assertions. */
export function installFetchMock(responder: Responder) {
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/health') && !url.includes('/health/ready')) {
      return jsonResponse(200, { status: 'ok' })
    }
    const { status, body } = await responder(url, init)
    return jsonResponse(status, body)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response
}
