import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from './test/mockFetch'
import { ADMIN_ACCOUNT, MEMBER_ACCOUNT, renderApp } from './test/renderApp'

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

    renderApp('/system', ADMIN_ACCOUNT)

    await waitFor(() => {
      expect(screen.getByText(/Database \(PostgreSQL\)/i)).toBeInTheDocument()
    })
  })
})

describe('administrator-only screens', () => {
  const EVERYONE = ['Copilot', 'Conversations', 'Documents', 'Memory', 'Operations']
  const systemStatusCalls = (fetchMock: ReturnType<typeof installFetchMock>) =>
    fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/v1/system/status'))

  it('lists System Status for an administrator', () => {
    installFetchMock(() => ({ status: 200, body: {} }))
    renderApp('/', ADMIN_ACCOUNT)

    for (const name of EVERYONE) expect(screen.getByRole('link', { name })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'System Status' })).toHaveAttribute('href', '/system')
  })

  it('hides System Status from a member, who keeps every other page', () => {
    installFetchMock(() => ({ status: 200, body: {} }))
    renderApp('/', MEMBER_ACCOUNT)

    for (const name of EVERYONE) expect(screen.getByRole('link', { name })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'System Status' })).not.toBeInTheDocument()
  })

  it.each([
    ['a member', MEMBER_ACCOUNT],
    ['an unknown account', null],
  ])('shows %s who opens /system a notice and never calls the admin-only endpoint', async (_, account) => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: {} }))
    renderApp('/system', account)

    expect(await screen.findByText('Administrators only')).toBeInTheDocument()
    expect(screen.queryByText(/Database \(PostgreSQL\)/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'System Status' })).not.toBeInTheDocument()
    expect(systemStatusCalls(fetchMock)).toHaveLength(0)
  })

  it('an administrator who opens /system gets the page and its status request', async () => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: {} }))
    renderApp('/system', ADMIN_ACCOUNT)

    expect(await screen.findByText(/Database \(PostgreSQL\)/i)).toBeInTheDocument()
    expect(screen.queryByText('Administrators only')).not.toBeInTheDocument()
    await waitFor(() => expect(systemStatusCalls(fetchMock)).toHaveLength(1))
  })
})
