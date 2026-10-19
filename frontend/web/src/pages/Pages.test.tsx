import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import { renderApp } from '../test/renderApp'

const DOC = {
  id: '11111111-2222-3333-4444-555555555555',
  filename: 'policy.pdf',
  content_type: 'application/pdf',
  document_type: 'pdf',
  file_size: 2048,
  status: 'processed',
  error_message: null,
  page_count: 3,
  character_count: 900,
  metadata: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  processed_at: '2026-01-01T00:01:00Z',
}

describe('Documents page', () => {
  it('shows the empty state', async () => {
    installFetchMock(() => ({ status: 200, body: { items: [], total: 0 } }))
    renderApp('/documents')
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
  })

  it('lists documents with a status label and exposes the id in details', async () => {
    installFetchMock(() => ({ status: 200, body: { items: [DOC], total: 1 } }))
    renderApp('/documents')
    expect(await screen.findByText('policy.pdf')).toBeInTheDocument()
    expect(screen.getByText('Processed')).toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: 'Details for policy.pdf' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(DOC.id)).toBeInTheDocument()
  })

  it('loads chunks only on demand', async () => {
    const fetchMock = installFetchMock((url) => {
      if (url.includes('/chunks')) {
        return {
          status: 200,
          body: {
            items: [
              {
                id: 'c1',
                chunk_index: 0,
                content: 'first chunk text',
                character_count: 16,
                token_count: null,
                metadata: null,
                created_at: DOC.created_at,
              },
            ],
            total: 4,
          },
        }
      }
      return { status: 200, body: { items: [DOC], total: 1 } }
    })
    renderApp('/documents')
    await userEvent.click(await screen.findByRole('button', { name: 'Details for policy.pdf' }))
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/chunks'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'View chunks' }))
    expect(await screen.findByText('first chunk text')).toBeInTheDocument()
    expect(screen.getByText('Showing 1 of 4 chunks.')).toBeInTheDocument()
  })

  it('shows a clear message when the API answers 401', async () => {
    installFetchMock(() => ({
      status: 401,
      body: { error: { code: 'unauthorized', message: 'raw' } },
    }))
    renderApp('/documents')
    expect(await screen.findByRole('alert')).toHaveTextContent(/not signed in/i)
  })
})

describe('Operations page', () => {
  it('shows only real counts from the backend', async () => {
    installFetchMock(() => ({
      status: 200,
      body: { total_documents: 5, documents_by_status: { processed: 4, failed: 1 } },
    }))
    renderApp('/operations')
    expect(await screen.findByText('Total documents')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('Processed')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.queryByText(/requests|executions|latency/i)).not.toBeInTheDocument()
  })

  it('shows an error state instead of fabricated numbers', async () => {
    installFetchMock(() => ({
      status: 503,
      body: { error: { code: 'x', message: 'down' } },
    }))
    renderApp('/operations')
    expect(await screen.findByText('Could not load operations data')).toBeInTheDocument()
    expect(screen.queryByText('Total documents')).not.toBeInTheDocument()
  })
})

describe('System status page', () => {
  it('separates live checks from configuration and never blanket-reports healthy', async () => {
    installFetchMock(() => ({
      status: 200,
      body: {
        database: 'ok',
        redis: 'unavailable',
        llm_configured: false,
        trusted_a2a_agents: [],
        mcp_server: '',
      },
    }))
    renderApp('/system')
    // redis down and LLM not configured both render as Unavailable; database is the only Healthy row
    await waitFor(() => expect(screen.getAllByText('Unavailable')).toHaveLength(2))
    expect(screen.getAllByText('Healthy')).toHaveLength(1)
    expect(screen.getByText(/not a live provider call/i)).toBeInTheDocument()
  })

  it('shows an alert when the status call fails', async () => {
    installFetchMock(() => ({
      status: 503,
      body: { error: { code: 'x', message: 'down' } },
    }))
    renderApp('/system')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument()
  })
})
