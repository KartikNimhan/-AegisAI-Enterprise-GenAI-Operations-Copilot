import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import { chunk, installStreamingFetch } from '../test/mockStream'
import { CopilotPage } from './CopilotPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CopilotPage (multi-agent workflow mode)', () => {
  it('sends a message and renders the returned answer', async () => {
    installFetchMock(async (url) => {
      if (url.includes('/api/v1/multi-agent/run')) {
        return {
          status: 200,
          body: {
            workflow_id: 'wf-1',
            correlation_id: 'corr-1',
            status: 'completed',
            answer: 'The expense limit is $500.',
            agents_used: [
              { agent_name: 'research', capability: 'research', status: 'completed', error: null, duration_ms: 120, retry_count: 0 },
            ],
            sources: [],
            token_usage: {},
            duration_ms: 150,
          },
        }
      }
      return { status: 200, body: {} }
    })

    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'workflow')

    const input = screen.getByPlaceholderText(/ask the copilot/i)
    await userEvent.type(input, 'What is the expense limit?')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))

    expect(screen.getByText('What is the expense limit?')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('The expense limit is $500.')).toBeInTheDocument()
    })
  })

  it('shows a friendly error message when the backend is unreachable', async () => {
    installFetchMock(async (url) => {
      if (url.includes('/api/v1/multi-agent/run')) {
        throw new Error('network down')
      }
      return { status: 200, body: {} }
    })

    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'workflow')

    const input = screen.getByPlaceholderText(/ask the copilot/i)
    await userEvent.type(input, 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))

    await waitFor(() => {
      expect(screen.getByText(/unable to reach the backend/i)).toBeInTheDocument()
    })
  })

  it('disables the composer while a request is in flight', async () => {
    let resolveRequest: (() => void) | undefined
    installFetchMock(async (url) => {
      if (url.includes('/api/v1/multi-agent/run')) {
        await new Promise<void>((resolve) => {
          resolveRequest = resolve
        })
        return { status: 200, body: { workflow_id: 'w', correlation_id: 'c', status: 'completed', answer: 'done', agents_used: [], sources: [], token_usage: {}, duration_ms: 1 } }
      }
      return { status: 200, body: {} }
    })

    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'workflow')
    const input = screen.getByPlaceholderText(/ask the copilot/i)
    await userEvent.type(input, 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))

    expect(screen.getByRole('button', { name: /send message/i })).toBeDisabled()
    resolveRequest?.()
  })
})

async function ask(message: string) {
  await userEvent.type(screen.getByPlaceholderText(/ask the copilot/i), message)
  await userEvent.click(screen.getByRole('button', { name: /send message/i }))
}

describe('CopilotPage (streamed mode)', () => {
  it('shows the answer incrementally, then the sources, and re-enables the composer', async () => {
    const { stream, requests } = installStreamingFetch()
    render(<CopilotPage />)

    await ask('What is the limit?')
    expect(screen.getByText('What is the limit?')).toBeInTheDocument()
    expect(screen.getByText(/thinking/i)).toBeInTheDocument() // loading state before the first chunk
    expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeDisabled()
    await waitFor(() => expect(requests).toHaveLength(1))

    stream.frame(chunk('The limit '))
    await waitFor(() => expect(screen.getByText(/The limit/)).toBeInTheDocument())
    expect(screen.queryByText(/thinking/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop generating/i })).toBeInTheDocument()

    stream.frame(chunk('is $500 [S1].'))
    await waitFor(() => expect(screen.getByText(/The limit is \$500 \[S1\]\./)).toBeInTheDocument())

    stream.frame(
      chunk('', {
        is_final: true,
        sources: [
          { source_id: 'S1', document_id: 'd', filename: 'Policy.pdf', chunk_index: 0, page: 4, similarity: 0.9, cited: true },
        ],
      }),
    )
    stream.done()

    await waitFor(() => expect(screen.getByLabelText('Sources')).toHaveTextContent('[S1] Policy.pdf · page 4'))
    expect(screen.queryByRole('button', { name: /stop generating/i })).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled()
  })

  it('keeps the partial answer and offers a retry when the stream fails mid-answer', async () => {
    const { stream, requests } = installStreamingFetch()
    render(<CopilotPage />)
    await ask('question')
    await waitFor(() => expect(requests).toHaveLength(1))

    stream.frame(chunk('Half an answer'))
    await waitFor(() => expect(screen.getByText('Half an answer')).toBeInTheDocument())
    stream.frame({ error: { code: 'LLMTimeoutError', message: 'The model timed out.' } })

    expect(await screen.findByRole('alert')).toHaveTextContent('The model timed out.')
    expect(screen.getByText('Half an answer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled()
  })

  it('retry sends the same message again and replaces the failed answer', async () => {
    const first = installStreamingFetch()
    render(<CopilotPage />)
    await ask('question')
    await waitFor(() => expect(first.requests).toHaveLength(1))
    first.stream.break()
    const retry = await screen.findByRole('button', { name: /try again/i })

    const second = installStreamingFetch()
    await userEvent.click(retry)
    await waitFor(() => expect(second.requests).toHaveLength(1))
    expect(second.requests[0].body).toMatchObject({ message: 'question' })
    second.stream.frame(chunk('Recovered', { is_final: true, sources: [] }))
    second.stream.done()

    await waitFor(() => expect(screen.getByText('Recovered')).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getAllByText('question')).toHaveLength(1) // not duplicated
  })

  it('stop keeps what arrived, marks it stopped and frees the composer', async () => {
    const { stream, requests } = installStreamingFetch()
    render(<CopilotPage />)
    await ask('question')
    await waitFor(() => expect(requests).toHaveLength(1))
    stream.frame(chunk('Partial text'))
    await waitFor(() => expect(screen.getByText('Partial text')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /stop generating/i }))

    await waitFor(() => expect(screen.getByText('Stopped.')).toBeInTheDocument())
    expect(screen.getByText('Partial text')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled()
  })

  it('shows a friendly error when the backend rejects the request before streaming', async () => {
    installStreamingFetch({ status: 403, errorBody: { error: { code: 'forbidden', message: 'Access denied' } } })
    render(<CopilotPage />)

    await ask('question')

    expect(await screen.findByRole('alert')).toHaveTextContent(/do not have permission/i)
  })

  it('continues the same conversation, and a new conversation starts a fresh one', async () => {
    const one = installStreamingFetch()
    render(<CopilotPage />)
    await ask('first')
    await waitFor(() => expect(one.requests).toHaveLength(1))
    expect(one.requests[0].body).toEqual({ message: 'first' })
    one.stream.frame(chunk('A', { is_final: true, sources: [] }))
    one.stream.done()
    await waitFor(() => expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled())

    const two = installStreamingFetch()
    await ask('second')
    await waitFor(() => expect(two.requests).toHaveLength(1))
    expect(two.requests[0].body).toEqual({ message: 'second', conversation_id: 'conv-1' })
    two.stream.frame(chunk('B', { is_final: true, sources: [] }))
    two.stream.done()
    await waitFor(() => expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled())

    await userEvent.click(screen.getByRole('button', { name: /new conversation/i }))
    const three = installStreamingFetch()
    await ask('third')
    await waitFor(() => expect(three.requests).toHaveLength(1))
    expect(three.requests[0].body).toEqual({ message: 'third' })
  })

  it('cancels an answer that is still arriving when the page is left', async () => {
    const { requests, fetchMock } = installStreamingFetch()
    const { unmount } = render(<CopilotPage />)
    await ask('question')
    await waitFor(() => expect(requests).toHaveLength(1))
    const init = fetchMock.mock.calls.find(([url]) => String(url).includes('/rag/chat/stream'))?.[1]

    unmount()

    expect(init?.signal?.aborted).toBe(true)
  })
})

describe('CopilotPage (plain chat and agent modes)', () => {
  it('plain chat streams from the chat endpoint, with no sources', async () => {
    const { stream, requests } = installStreamingFetch({ path: '/api/v1/chat/completions/stream' })
    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'chat')

    await ask('hello')
    await waitFor(() => expect(requests).toHaveLength(1))
    stream.frame(chunk('Hi there', { is_final: true }))
    stream.done()

    expect(await screen.findByText('Hi there')).toBeInTheDocument()
    expect(screen.queryByLabelText('Sources')).not.toBeInTheDocument()
    expect(requests[0].url).toContain('/api/v1/chat/completions/stream')
  })

  it('agent mode shows each tool step and then the answer, and keeps the conversation id', async () => {
    const first = installStreamingFetch({ path: '/api/v1/agents/run/stream' })
    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'agent')

    await ask('what is 250 * 0.18?')
    await waitFor(() => expect(first.requests).toHaveLength(1))
    first.stream.event('tool_started', { tool_name: 'calculator' })
    expect(await screen.findByLabelText('Tools used')).toHaveTextContent('calculator — running')
    first.stream.event('tool_completed', { tool_name: 'calculator', success: true })
    await waitFor(() => expect(screen.getByLabelText('Tools used')).toHaveTextContent('calculator — done'))
    first.stream.event('answer_delta', { delta: 'It is 45.' })
    first.stream.event('completed', { status: 'completed', conversation_id: 'agent-conv-1' })

    expect(await screen.findByText('It is 45.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByPlaceholderText(/ask the copilot/i)).toBeEnabled())

    const second = installStreamingFetch({ path: '/api/v1/agents/run/stream' })
    await ask('and double it?')
    await waitFor(() => expect(second.requests).toHaveLength(1))
    expect(second.requests[0].body).toEqual({ message: 'and double it?', conversation_id: 'agent-conv-1' })
  })

  it('agent mode marks a failed tool and shows a stream error with a retry', async () => {
    const { stream, requests } = installStreamingFetch({ path: '/api/v1/agents/run/stream' })
    render(<CopilotPage />)
    await userEvent.selectOptions(screen.getByLabelText(/answer mode/i), 'agent')

    await ask('question')
    await waitFor(() => expect(requests).toHaveLength(1))
    stream.event('tool_started', { tool_name: 'search_knowledge_base' })
    stream.event('tool_completed', { tool_name: 'search_knowledge_base', success: false })
    stream.event('error', { error: { code: 'AgentTimeoutError', message: 'The agent took too long.' } })

    expect(await screen.findByRole('alert')).toHaveTextContent('The agent took too long.')
    expect(screen.getByLabelText('Tools used')).toHaveTextContent('search_knowledge_base — failed')
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })
})

describe('CopilotPage (continuing a saved conversation)', () => {
  const CONV = '33333333-3333-3333-3333-333333333333'

  it('loads the saved messages and sends the next message to the same conversation', async () => {
    const { stream, requests } = installStreamingFetch({
      others: (url) =>
        url.endsWith(CONV)
          ? {
              status: 200,
              body: {
                id: CONV,
                title: 'Earlier',
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
                messages: [
                  { id: 'a', role: 'user', content: 'Earlier question', created_at: '2026-01-01T00:00:00Z' },
                  { id: 'b', role: 'assistant', content: 'Earlier answer', created_at: '2026-01-01T00:00:01Z' },
                ],
              },
            }
          : { status: 200, body: {} },
    })
    render(<CopilotPage initialConversationId={CONV} />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading conversation')
    expect(await screen.findByText('Earlier answer')).toBeInTheDocument()
    expect(screen.getByText('Earlier question')).toBeInTheDocument()

    await ask('follow up')
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0].body).toEqual({ message: 'follow up', conversation_id: CONV })
    stream.done()
  })

  it('says so when the conversation cannot be opened', async () => {
    installStreamingFetch({
      others: () => ({ status: 404, body: { error: { code: 'not_found', message: 'Conversation not found' } } }),
    })
    render(<CopilotPage initialConversationId={CONV} />)

    expect(await screen.findByText('Could not open that conversation')).toBeInTheDocument()
    expect(screen.getByText('Conversation not found')).toBeInTheDocument()
  })
})
