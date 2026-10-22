import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendError } from './client'
import { streamRagChat } from './stream'
import type { StreamChunk } from './stream'
import { chunk, installStreamingFetch } from '../test/mockStream'

afterEach(() => {
  vi.unstubAllGlobals()
})

const text = (chunks: StreamChunk[]) => chunks.map((c) => c.delta).join('')

describe('streamRagChat', () => {
  it('delivers each chunk as it arrives and resolves on [DONE]', async () => {
    const { stream, requests } = installStreamingFetch()
    const chunks: StreamChunk[] = []
    const run = streamRagChat({ message: 'hi', onChunk: (c) => chunks.push(c) })

    await vi.waitFor(() => expect(requests).toHaveLength(1))
    stream.frame(chunk('Hel'))
    await vi.waitFor(() => expect(chunks.map((c) => c.delta)).toEqual(['Hel']))
    stream.frame(chunk('lo', { is_final: true, sources: [] }))
    stream.done()
    await run

    expect(text(chunks)).toBe('Hello')
    expect(chunks[1].is_final).toBe(true)
  })

  it('sends the message, the conversation id and the accept header to the streaming endpoint', async () => {
    const { stream, requests } = installStreamingFetch()
    const run = streamRagChat({ message: 'q', conversationId: 'c-9', onChunk: () => undefined })
    await vi.waitFor(() => expect(requests).toHaveLength(1))
    stream.done()
    await run

    expect(requests[0].url).toContain('/api/v1/rag/chat/stream')
    expect(requests[0].body).toEqual({ message: 'q', conversation_id: 'c-9' })
    expect(requests[0].headers.Accept).toBe('text/event-stream')
  })

  it('reassembles frames split across network chunks and tolerates CRLF', async () => {
    const { stream, requests } = installStreamingFetch()
    const chunks: StreamChunk[] = []
    const run = streamRagChat({ message: 'q', onChunk: (c) => chunks.push(c) })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    const frame = `data: ${JSON.stringify(chunk('Split'))}\r\n\r\n`
    stream.push(frame.slice(0, 10))
    stream.push(frame.slice(10, 30))
    stream.push(frame.slice(30))
    stream.push('data: [DONE]\r\n\r\n')
    stream.close()
    await run

    expect(text(chunks)).toBe('Split')
  })

  it('ignores comment lines', async () => {
    const { stream, requests } = installStreamingFetch()
    const chunks: StreamChunk[] = []
    const run = streamRagChat({ message: 'q', onChunk: (c) => chunks.push(c) })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.push(': keep-alive\n\n')
    stream.frame(chunk('ok'))
    stream.done()
    await run

    expect(text(chunks)).toBe('ok')
  })

  it('rejects with the server error carried by a terminal error frame, keeping earlier text', async () => {
    const { stream, requests } = installStreamingFetch()
    const chunks: StreamChunk[] = []
    const run = streamRagChat({ message: 'q', onChunk: (c) => chunks.push(c) })
    const assertion = expect(run).rejects.toMatchObject({
      name: 'BackendError',
      code: 'LLMTimeoutError',
      message: 'model timed out',
    })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.frame(chunk('partial'))
    stream.frame({ error: { code: 'LLMTimeoutError', message: 'model timed out' } })

    await assertion
    expect(text(chunks)).toBe('partial')
  })

  it('rejects as interrupted when the body closes without [DONE]', async () => {
    const { stream, requests } = installStreamingFetch()
    const run = streamRagChat({ message: 'q', onChunk: () => undefined })
    const assertion = expect(run).rejects.toMatchObject({ code: 'stream_interrupted' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.frame(chunk('half an ans'))
    stream.close()

    await assertion
  })

  it('rejects as interrupted when the connection breaks mid-stream', async () => {
    const { stream, requests } = installStreamingFetch()
    const run = streamRagChat({ message: 'q', onChunk: () => undefined })
    const assertion = expect(run).rejects.toMatchObject({ code: 'stream_interrupted' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.break()

    await assertion
  })

  it('rejects with malformed_response for a frame that is not JSON', async () => {
    const { stream, requests } = installStreamingFetch()
    const run = streamRagChat({ message: 'q', onChunk: () => undefined })
    const assertion = expect(run).rejects.toMatchObject({ code: 'malformed_response' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.push('data: {not json\n\n')

    await assertion
  })

  it('turns an HTTP error before streaming into a BackendError with the server code', async () => {
    installStreamingFetch({
      status: 404,
      errorBody: { error: { code: 'not_found', message: 'Conversation not found' } },
    })

    const error = await streamRagChat({ message: 'q', onChunk: () => undefined }).catch((e) => e)

    expect(error).toBeInstanceOf(BackendError)
    expect(error).toMatchObject({ code: 'not_found', statusCode: 404 })
  })

  it('reports an unreachable backend as network_error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    await expect(streamRagChat({ message: 'q', onChunk: () => undefined })).rejects.toMatchObject({
      code: 'network_error',
    })
  })

  it('rejects with an AbortError when cancelled and delivers nothing afterwards', async () => {
    const { stream, requests } = installStreamingFetch()
    const abort = new AbortController()
    const chunks: StreamChunk[] = []
    const run = streamRagChat({ message: 'q', signal: abort.signal, onChunk: (c) => chunks.push(c) })
    const assertion = expect(run).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))
    stream.frame(chunk('a'))
    await vi.waitFor(() => expect(chunks).toHaveLength(1))

    abort.abort()

    await assertion
    expect(chunks).toHaveLength(1)
  })
})
