import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from './test/mockFetch'
import { renderApp } from './test/renderApp'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('navigation', () => {
  it('shows the Copilot page by default and navigates to Documents', async () => {
    installFetchMock(async (url) => {
      if (url.includes('/api/v1/documents')) return { status: 200, body: { items: [], total: 0 } }
      return { status: 200, body: {} }
    })

    renderApp('/')
    expect(screen.getByText(/No messages yet/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: /documents/i }))

    await waitFor(() => {
      expect(screen.getByText(/No documents yet/i)).toBeInTheDocument()
    })
  })

  it('navigates to System Status and renders dependency rows', async () => {
    installFetchMock(async (url) => {
      if (url.includes('/api/v1/system/status')) {
        return {
          status: 200,
          body: {
            database: 'ok',
            redis: 'unavailable',
            llm_configured: false,
            trusted_a2a_agents: ['http://localhost:8000'],
            mcp_server: 'aegisai-internal',
          },
        }
      }
      return { status: 200, body: {} }
    })

    renderApp('/system')

    await waitFor(() => {
      expect(screen.getByText(/Database \(PostgreSQL\)/i)).toBeInTheDocument()
    })
  })
})
