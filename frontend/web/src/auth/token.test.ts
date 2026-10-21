import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  authHeaders,
  getAccessToken,
  notifyUnauthorized,
  setAccessToken,
  setUnauthorizedHandler,
} from './token'

afterEach(() => {
  setAccessToken(null)
  setUnauthorizedHandler(null)
})

describe('token bridge', () => {
  it('sends no Authorization header while signed out', () => {
    expect(getAccessToken()).toBeNull()
    expect(authHeaders()).toEqual({})
  })

  it('sends the current bearer token once set, and stops when cleared', () => {
    setAccessToken('abc.def.ghi')
    expect(authHeaders()).toEqual({ Authorization: 'Bearer abc.def.ghi' })

    setAccessToken(null)
    expect(authHeaders()).toEqual({})
  })

  it('reports a 401 to the registered handler, and is harmless without one', () => {
    expect(() => notifyUnauthorized()).not.toThrow()

    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    notifyUnauthorized()

    expect(handler).toHaveBeenCalledTimes(1)
  })
})
