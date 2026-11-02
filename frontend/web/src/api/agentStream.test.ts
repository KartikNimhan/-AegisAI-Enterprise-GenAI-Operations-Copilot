import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendError } from './client'
import { streamAgentRun, streamPlainChat } from './stream'
import type { AgentStreamEvent, StreamChunk } from './stream'
import { chunk, installStreamingFetch } from '../test/mockStream'

afterEach(() => {
  vi.unstubAllGlobals()
})

const AGENT = '/api/v1/agents/run/stream'

describe('streamAgentRun', () => {
  it('delivers tool steps and the answer in order and resolves on completed', async () => {
    const { stream, requests } = installStreamingFetch({ path: AGENT })
    const events: AgentStreamEvent[] = []
    const run = streamAgentRun({ message: 'q', conversationId: 'c-1', onEvent: (e) => events.push(e) })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.event('tool_started', { tool_name: 'calculator' })
    stream.event('tool_completed', { tool_name: 'calculator', success: true })
    stream.event('answer_delta', { delta: '45' })
    stream.event('completed', { status: 'completed', conversation_id: 'c-1' })
    await run

    expect(requests[0].body).toEqual({ message: 'q', conversation_id: 'c-1' })
    expect(events).toEqual([
      { type: 'tool_started', toolName: 'calculator' },
      { type: 'tool_completed', toolName: 'calculator', success: true },
      { type: 'answer_delta', delta: '45' },
      { type: 'completed', status: 'completed', conversationId: 'c-1' },
    ])
  })

  it('rejects when the server sends a terminal error event', async () => {
    const { stream, requests } = installStreamingFetch({ path: AGENT })
    const run = streamAgentRun({ message: 'q', onEvent: () => undefined })
    const assertion = expect(run).rejects.toMatchObject({ code: 'AgentTimeoutError' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.event('error', { error: { code: 'AgentTimeoutError', message: 'Agent run exceeded 60s' } })

    await assertion
  })

  it('rejects as interrupted when the stream ends without a completed event', async () => {
    const { stream, requests } = installStreamingFetch({ path: AGENT })
    const run = streamAgentRun({ message: 'q', onEvent: () => undefined })
    const assertion = expect(run).rejects.toMatchObject({ code: 'stream_interrupted' })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.event('answer_delta', { delta: 'half' })
    stream.close()

    await assertion
  })

  it('treats a frame that is not a JSON object as a malformed response', async () => {
    const { stream, requests } = installStreamingFetch({ path: AGENT })
    const run = streamAgentRun({ message: 'q', onEvent: () => undefined })
    const assertion = expect(run).rejects.toBeInstanceOf(BackendError)
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.push('event: answer_delta\ndata: not json\n\n')

    await assertion
  })

  it('ignores an event it does not know instead of failing', async () => {
    const { stream, requests } = installStreamingFetch({ path: AGENT })
    const events: AgentStreamEvent[] = []
    const run = streamAgentRun({ message: 'q', onEvent: (e) => events.push(e) })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.event('future_event', { anything: true })
    stream.event('completed', { status: 'completed' })
    await run

    expect(events).toEqual([{ type: 'completed', status: 'completed', conversationId: null }])
  })
})

describe('streamPlainChat', () => {
  it('uses the plain chat endpoint and the same chunk contract', async () => {
    const { stream, requests } = installStreamingFetch({ path: '/api/v1/chat/completions/stream' })
    const chunks: StreamChunk[] = []
    const run = streamPlainChat({ message: 'hi', onChunk: (c) => chunks.push(c) })
    await vi.waitFor(() => expect(requests).toHaveLength(1))

    stream.frame(chunk('Hello', { is_final: true }))
    stream.done()
    await run

    expect(requests[0].url).toContain('/api/v1/chat/completions/stream')
    expect(chunks.map((c) => c.delta)).toEqual(['Hello'])
  })
})
