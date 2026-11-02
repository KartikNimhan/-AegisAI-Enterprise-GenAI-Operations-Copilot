import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import { renderApp } from '../test/renderApp'

afterEach(() => {
  vi.unstubAllGlobals()
})

const CONVERSATION = {
  id: '11111111-1111-1111-1111-111111111111',
  title: 'Travel policy',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

const MEMORY = {
  id: '22222222-2222-2222-2222-222222222222',
  kind: 'preference',
  source: 'agent',
  content: 'Prefers short answers',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  expires_at: '2026-04-01T00:00:00Z',
}

describe('Conversations page', () => {
  it('shows a loading state, then an empty state with a way forward', async () => {
    installFetchMock(() => ({ status: 200, body: [] }))
    renderApp('/conversations')

    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(await screen.findByText('No conversations yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Copilot' })).toHaveAttribute('href', '/')
  })

  it('shows an error with a retry that works', async () => {
    let attempts = 0
    installFetchMock(() => {
      attempts += 1
      return attempts === 1
        ? { status: 503, body: { error: { code: 'unavailable', message: 'down' } } }
        : { status: 200, body: [CONVERSATION] }
    })
    renderApp('/conversations')

    expect(await screen.findByText('Could not load your conversations')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Travel policy')).toBeInTheDocument()
  })

  it('opens a conversation to read its messages', async () => {
    installFetchMock((url) =>
      url.endsWith(CONVERSATION.id)
        ? {
            status: 200,
            body: {
              ...CONVERSATION,
              messages: [
                { id: 'm1', role: 'user', content: 'What can I claim?', created_at: CONVERSATION.created_at },
                { id: 'm2', role: 'assistant', content: 'Economy fares.', created_at: CONVERSATION.created_at },
              ],
            },
          }
        : { status: 200, body: [CONVERSATION] },
    )
    renderApp('/conversations')

    await userEvent.click(await screen.findByRole('button', { name: 'Open Travel policy' }))

    const messages = await screen.findByRole('list', { name: 'Messages' })
    expect(within(messages).getByText(/What can I claim\?/)).toBeInTheDocument()
    expect(within(messages).getByText(/Economy fares\./)).toBeInTheDocument()
  })

  it('links to the Copilot with the conversation id to continue it', async () => {
    installFetchMock(() => ({ status: 200, body: [CONVERSATION] }))
    renderApp('/conversations')

    expect(await screen.findByRole('link', { name: 'Continue' })).toHaveAttribute(
      'href',
      `/?conversation=${CONVERSATION.id}`,
    )
  })

  it('asks for confirmation before deleting, and cancel deletes nothing', async () => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: [CONVERSATION] }))
    renderApp('/conversations')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Travel policy' }))
    expect(screen.getByRole('button', { name: 'Confirm delete Travel policy' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('button', { name: /confirm delete/i })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('deletes after confirmation and removes the row', async () => {
    const fetchMock = installFetchMock((_url, init) =>
      init?.method === 'DELETE' ? { status: 204, body: null } : { status: 200, body: [CONVERSATION] },
    )
    renderApp('/conversations')

    await userEvent.click(await screen.findByRole('button', { name: 'Delete Travel policy' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete Travel policy' }))

    await waitFor(() => expect(screen.getByText('No conversations yet')).toBeInTheDocument())
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url).endsWith(CONVERSATION.id) && init?.method === 'DELETE',
      ),
    ).toBe(true)
  })
})

describe('Memory page', () => {
  it('lists notes with their kind and who wrote them', async () => {
    installFetchMock(() => ({ status: 200, body: [MEMORY] }))
    renderApp('/memory')

    expect(await screen.findByText('Prefers short answers')).toBeInTheDocument()
    expect(screen.getByText(/preference · saved by the agent/)).toBeInTheDocument()
  })

  it('shows an empty state and an error state', async () => {
    installFetchMock(() => ({ status: 200, body: [] }))
    const { unmount } = renderApp('/memory')
    expect(await screen.findByText('Nothing remembered yet')).toBeInTheDocument()
    unmount()

    installFetchMock(() => ({ status: 503, body: { error: { code: 'x', message: 'down' } } }))
    renderApp('/memory')
    expect(await screen.findByText('Could not load your memory')).toBeInTheDocument()
  })

  it('adds a note', async () => {
    const fetchMock = installFetchMock((_url, init) =>
      init?.method === 'POST'
        ? { status: 201, body: { ...MEMORY, source: 'user', kind: 'fact', content: 'Works in Pune' } }
        : { status: 200, body: [] },
    )
    renderApp('/memory')
    await screen.findByText('Nothing remembered yet')

    await userEvent.type(screen.getByLabelText('New note'), '  Works in Pune ')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))

    expect(await screen.findByText('Works in Pune')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ content: 'Works in Pune', kind: 'fact' })
  })

  it('shows the server message when the memory is full', async () => {
    installFetchMock((_url, init) =>
      init?.method === 'POST'
        ? { status: 409, body: { error: { code: 'memory_full', message: 'The memory is full (200 notes).' } } }
        : { status: 200, body: [MEMORY] },
    )
    renderApp('/memory')
    await screen.findByText('Prefers short answers')

    await userEvent.type(screen.getByLabelText('New note'), 'one more')
    await userEvent.click(screen.getByRole('button', { name: 'Save note' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The memory is full (200 notes).')
    expect(screen.getByLabelText('New note')).toHaveValue('one more') // nothing is lost
  })

  it('edits a note', async () => {
    const fetchMock = installFetchMock((_url, init) =>
      init?.method === 'PATCH'
        ? { status: 200, body: { ...MEMORY, content: 'Prefers detailed answers' } }
        : { status: 200, body: [MEMORY] },
    )
    renderApp('/memory')

    await userEvent.click(await screen.findByRole('button', { name: /Edit note: Prefers short answers/ }))
    const box = screen.getByLabelText('Edit note')
    await userEvent.clear(box)
    await userEvent.type(box, 'Prefers detailed answers')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Prefers detailed answers')).toBeInTheDocument()
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(String(patch?.[0])).toContain(MEMORY.id)
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ content: 'Prefers detailed answers' })
  })

  it('deletes one note only after confirmation', async () => {
    const fetchMock = installFetchMock((_url, init) =>
      init?.method === 'DELETE' ? { status: 204, body: null } : { status: 200, body: [MEMORY] },
    )
    renderApp('/memory')

    await userEvent.click(await screen.findByRole('button', { name: /Delete note: Prefers short answers/ }))
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: /Confirm delete note/ }))

    await waitFor(() => expect(screen.getByText('Nothing remembered yet')).toBeInTheDocument())
  })

  it('forgets everything only after confirmation and reports how many', async () => {
    installFetchMock((_url, init) =>
      init?.method === 'DELETE' ? { status: 200, body: { deleted: 1 } } : { status: 200, body: [MEMORY] },
    )
    renderApp('/memory')

    await userEvent.click(await screen.findByRole('button', { name: 'Forget everything' }))
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm forget all' }))

    expect(await screen.findByText('Forgot 1 note.')).toBeInTheDocument()
    expect(screen.getByText('Nothing remembered yet')).toBeInTheDocument()
  })
})
