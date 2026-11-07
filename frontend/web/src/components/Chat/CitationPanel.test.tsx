/** M10.5: the citation source panel. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../../test/mockFetch'
import { expectAxe } from '../../test/axe'
import { CitationPanel, type CitationTarget, SUPPORT_NOT_VERIFIED } from './CitationPanel'

afterEach(() => vi.unstubAllGlobals())

const TARGET: CitationTarget = { conversationId: 'c1', messageId: 'm1', sourceId: 'S1' }

function available(overrides: Record<string, unknown> = {}) {
  return {
    status: 'available',
    message_id: 'm1',
    source_id: 'S1',
    cited: true,
    support: 'not_verified',
    document_id: 'd1',
    chunk_id: 'k1',
    filename: 'Travel Policy.pdf',
    chunk_index: 3,
    page: 2,
    section: 'Expenses > Travel',
    similarity: 0.8,
    passage: { text: 'Employees may claim economy fares.', characters: 34, truncated: false },
    neighbors: null,
    ...overrides,
  }
}

function Harness({ target = TARGET }: { target?: CitationTarget }) {
  const [open, setOpen] = useState<CitationTarget | null>(null)
  return (
    <MemoryRouter>
      <button type="button" onClick={() => setOpen(target)}>
        Open citation
      </button>
      <CitationPanel target={open} onClose={() => setOpen(null)} />
    </MemoryRouter>
  )
}

async function openPanel() {
  const user = userEvent.setup()
  render(<Harness />)
  await user.click(screen.getByRole('button', { name: 'Open citation' }))
  return user
}

describe('CitationPanel', () => {
  it('shows the passage, its location and the not-verified label', async () => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: available() }))
    await openPanel()

    const dialog = await screen.findByRole('dialog', { name: 'Source S1' })
    expect(await screen.findByText('Employees may claim economy fares.')).toBeInTheDocument()
    expect(dialog).toHaveTextContent(SUPPORT_NOT_VERIFIED)
    expect(dialog).toHaveTextContent('Page 2 · Section: Expenses > Travel · Passage 4')
    expect(screen.getByRole('link', { name: 'Travel Policy.pdf' })).toHaveAttribute('href', '/documents/d1?chunk=3')
    expect(dialog).not.toHaveTextContent(/supported by|proves|verified source/i)
    expect(String(fetchMock.mock.calls.find(([u]) => String(u).includes('citations'))?.[0])).toContain(
      '/api/v1/conversations/c1/messages/m1/citations/S1',
    )
    await expectAxe(document.body)
  })

  it('says when only the start of the passage reached the model', async () => {
    installFetchMock(() => ({
      status: 200,
      body: available({ passage: { text: 'Start', characters: 5, truncated: true } }),
    }))
    await openPanel()

    expect(await screen.findByText(/only the start of this passage reached the model/i)).toBeInTheDocument()
  })

  it('shows an unavailable source without any of its details', async () => {
    installFetchMock(() => ({
      status: 200,
      body: { status: 'unavailable', message_id: 'm1', source_id: 'S1', cited: true, support: 'not_verified' },
    }))
    await openPanel()

    expect(await screen.findByText('This source is no longer available')).toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /surrounding text/i })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent(SUPPORT_NOT_VERIFIED)
  })

  it('loads up to two neighbouring passages on request', async () => {
    const urls: string[] = []
    installFetchMock((url) => {
      urls.push(url)
      return url.includes('neighbors=2')
        ? {
            status: 200,
            body: available({
              neighbors: {
                before: [{ chunk_id: 'k0', chunk_index: 2, page: 2, section: null, text: 'Before text' }],
                after: [{ chunk_id: 'k4', chunk_index: 4, page: 3, section: null, text: 'After text' }],
              },
            }),
          }
        : { status: 200, body: available() }
    })
    const user = await openPanel()
    await screen.findByText('Employees may claim economy fares.')

    await user.click(screen.getByRole('button', { name: 'Show surrounding text' }))

    expect(await screen.findByText('Before text')).toBeInTheDocument()
    expect(screen.getByText('After text')).toBeInTheDocument()
    expect(urls.some((u) => u.includes('neighbors=2'))).toBe(true)
    expect(urls.some((u) => /neighbors=([3-9]|\d{2,})/.test(u))).toBe(false)
    expect(screen.getByRole('button', { name: 'Hide surrounding text' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('treats a 404 as a source that cannot be found', async () => {
    installFetchMock(() => ({ status: 404, body: { error: { code: 'not_found', message: 'Citation not found' } } }))
    await openPanel()

    expect(await screen.findByText('This source could not be found')).toBeInTheDocument()
  })

  it('offers a retry when loading fails', async () => {
    let calls = 0
    installFetchMock(() => {
      calls += 1
      return calls === 1
        ? { status: 500, body: { error: { code: 'internal_error', message: 'boom' } } }
        : { status: 200, body: available() }
    })
    const user = await openPanel()

    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Employees may claim economy fares.')).toBeInTheDocument()
  })

  it('closes with Escape and returns focus to what opened it', async () => {
    installFetchMock(() => ({ status: 200, body: available() }))
    const user = await openPanel()
    await screen.findByRole('dialog')

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Open citation' })).toHaveFocus()
  })
})
