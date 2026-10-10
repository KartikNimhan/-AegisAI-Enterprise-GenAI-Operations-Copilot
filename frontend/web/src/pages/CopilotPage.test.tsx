import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import { CopilotPage } from './CopilotPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CopilotPage', () => {
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
    const input = screen.getByPlaceholderText(/ask the copilot/i)
    await userEvent.type(input, 'hello')
    await userEvent.click(screen.getByRole('button', { name: /send message/i }))

    expect(screen.getByRole('button', { name: /send message/i })).toBeDisabled()
    resolveRequest?.()
  })
})
