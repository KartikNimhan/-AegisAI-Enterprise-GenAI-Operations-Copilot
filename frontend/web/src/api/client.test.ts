import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendError, requestJson } from './client'
import { setAccessToken, setUnauthorizedHandler } from '../auth/token'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('requestJson', () => {
  it('parses the backend error envelope into a BackendError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          ({
            status: 404,
            ok: false,
            text: async () => JSON.stringify({ error: { message: 'Document not found', code: 'not_found' } }),
            json: async () => ({ error: { message: 'Document not found', code: 'not_found' } }),
          }) as unknown as Response,
      ),
    )

    await expect(requestJson('/api/v1/documents/missing')).rejects.toMatchObject({
      message: 'Document not found',
      code: 'not_found',
      statusCode: 404,
    })
  })

  it('maps a network failure to a BackendError with code network_error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    await expect(requestJson('/health')).rejects.toBeInstanceOf(BackendError)
    await expect(requestJson('/health')).rejects.toMatchObject({ code: 'network_error' })
  })

  it('returns null for a 204 No Content response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          ({
            status: 204,
            ok: true,
            text: async () => '',
            json: async () => {
              throw new Error('should not be called')
            },
          }) as unknown as Response,
      ),
    )

    await expect(requestJson('/api/v1/documents/abc', { method: 'DELETE', okStatusCodes: [204] })).resolves.toBeNull()
  })
})

describe('authentication', () => {
  function respond(status: number, body: unknown = {}) {
    const fetchMock = vi.fn(
      async (_url: unknown, _init?: RequestInit) =>
        ({
          status,
          ok: status >= 200 && status < 300,
          text: async () => JSON.stringify(body),
          json: async () => body,
        }) as unknown as Response,
    )
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  afterEach(() => {
    setAccessToken(null)
    setUnauthorizedHandler(null)
  })

  it('sends the bearer token when signed in, and none when signed out', async () => {
    const fetchMock = respond(200, { ok: true })

    await requestJson('/api/v1/documents')
    setAccessToken('tok-1')
    await requestJson('/api/v1/documents')
    await requestJson('/api/v1/chat', { method: 'POST', json: { a: 1 } })

    const headers = fetchMock.mock.calls.map(([, init]) => init?.headers)
    expect(headers[0]).toEqual({})
    expect(headers[1]).toEqual({ Authorization: 'Bearer tok-1' })
    expect(headers[2]).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer tok-1' })
  })

  it('tells the auth layer about a 401, still rejects, and does not do so for a 403', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)

    respond(401, { error: { code: 'unauthorized', message: 'Authentication required' } })
    await expect(requestJson('/api/v1/documents')).rejects.toMatchObject({ statusCode: 401 })
    expect(handler).toHaveBeenCalledTimes(1)

    respond(403, { error: { code: 'forbidden', message: 'Access denied' } })
    await expect(requestJson('/api/v1/auth/me')).rejects.toMatchObject({ statusCode: 403 })
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
