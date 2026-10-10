import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendError, requestJson } from './client'

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
