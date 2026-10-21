import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, setUnauthorizedHandler } from '../auth/token'
import { uploadDocumentWithProgress } from './documents'

/** Just enough of XMLHttpRequest for the upload helper; records what it was given. */
class FakeXhr {
  static last: FakeXhr
  headers: Record<string, string> = {}
  upload: { onprogress: null | ((e: unknown) => void) } = { onprogress: null }
  status = 0
  responseText = ''
  timeout = 0
  onload: null | (() => void) = null
  onerror: null | (() => void) = null
  ontimeout: null | (() => void) = null
  method = ''
  url = ''

  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  send() {}
}

afterEach(() => {
  vi.unstubAllGlobals()
  setAccessToken(null)
  setUnauthorizedHandler(null)
})

function upload() {
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
  return uploadDocumentWithProgress(new File(['x'], 'a.txt'), () => {})
}

describe('uploadDocumentWithProgress authentication', () => {
  it('sends the bearer token with the upload', () => {
    setAccessToken('tok-9')
    void upload()

    expect(FakeXhr.last.headers).toEqual({ Authorization: 'Bearer tok-9' })
  })

  it('sends no Authorization header when signed out', () => {
    void upload()

    expect(FakeXhr.last.headers).toEqual({})
  })

  it('reports a 401 to the auth layer and rejects with a BackendError', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    const result = upload()
    FakeXhr.last.status = 401
    FakeXhr.last.responseText = JSON.stringify({ error: { code: 'unauthorized', message: 'Authentication required' } })

    FakeXhr.last.onload?.()

    await expect(result).rejects.toMatchObject({ statusCode: 401, code: 'unauthorized' })
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
