/** M10.3/M10.5: citations in the Copilot conversation (streamed and reopened answers). */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chunk, installStreamingFetch } from '../test/mockStream'
import { CopilotPage } from './CopilotPage'

afterEach(() => vi.unstubAllGlobals())

const SOURCE = { source_id: 'S1', document_id: 'd1', filename: 'Policy.pdf', chunk_index: 0, page: 4, similarity: 0.9, cited: true }
const PASSAGE = {
  status: 'available',
  message_id: 'msg-1',
  source_id: 'S1',
  cited: true,
  support: 'not_verified',
  document_id: 'd1',
  chunk_id: 'k1',
  filename: 'Policy.pdf',
  chunk_index: 0,
  page: 4,
  section: null,
  similarity: 0.9,
  passage: { text: 'The limit is 500 per trip.', characters: 26, truncated: false },
  neighbors: null,
}

function renderPage(initialConversationId?: string) {
  return render(
    <MemoryRouter>
      <CopilotPage initialConversationId={initialConversationId} />
    </MemoryRouter>,
  )
}

async function ask(message: string) {
  await userEvent.type(screen.getByPlaceholderText(/ask the copilot/i), message)
  await userEvent.click(screen.getByRole('button', { name: /send message/i }))
}

describe('Copilot citations', () => {
  it('opens a streamed answer source only once the answer is saved', async () => {
    const citationUrls: string[] = []
    const { stream } = installStreamingFetch({
      others: (url) => {
        if (url.includes('/citations/')) {
          citationUrls.push(url)
          return { status: 200, body: PASSAGE }
        }
        return { status: 200, body: {} }
      },
    })
    renderPage()
    await ask('What is the limit?')

    stream.frame(chunk('The limit is 500 [S1].'))
    stream.frame(
      chunk('', {
        is_final: true,
        sources: [SOURCE],
        message_id: 'msg-1',
        conversation_id: 'conv-1',
        invalid_citations: ['S9'],
      }),
    )
    // Before [DONE], the reply is not saved yet: nothing can be opened.
    await waitFor(() => expect(screen.getByLabelText('Sources')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Open source S1' })).not.toBeInTheDocument()

    stream.done()

    const marker = await screen.findByRole('button', { name: 'Open source S1' })
    expect(screen.getByText(/The model cited S9, which was not among the retrieved sources/)).toBeInTheDocument()
    await userEvent.click(marker)

    expect(await screen.findByText('The limit is 500 per trip.')).toBeInTheDocument()
    expect(citationUrls[0]).toContain('/api/v1/conversations/conv-1/messages/msg-1/citations/S1')
    expect(await screen.findByText('The answer is complete.')).toBeInTheDocument()
  })

  it('cannot open citations of an answer whose stream broke after the final chunk', async () => {
    const { stream } = installStreamingFetch()
    renderPage()
    await ask('q')

    stream.frame(chunk('Answer [S1].', { is_final: true, sources: [SOURCE], message_id: 'msg-1', conversation_id: 'c' }))
    stream.close() // no [DONE]: the server rolled the reply back

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /open source|view source/i })).not.toBeInTheDocument()
  })

  it('a reopened conversation lists its saved citations, unavailable ones without details', async () => {
    const CONV = 'conv-saved'
    installStreamingFetch({
      others: (url) => {
        if (url.includes('/citations/S1')) return { status: 200, body: { ...PASSAGE, message_id: 'b' } }
        if (url.endsWith(CONV)) {
          return {
            status: 200,
            body: {
              id: CONV,
              title: 'Earlier',
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
              messages: [
                { id: 'a', role: 'user', content: 'Earlier question', created_at: '2026-01-01T00:00:00Z' },
                {
                  id: 'b',
                  role: 'assistant',
                  content: 'Earlier answer [S1] and [S2].',
                  created_at: '2026-01-01T00:00:01Z',
                  citations: [
                    { source_id: 'S1', status: 'available', cited: true, passage_truncated: false, support: 'not_verified', document_id: 'd1', chunk_id: 'k1', filename: 'Policy.pdf', chunk_index: 0, page: 4, section: null },
                    { source_id: 'S2', status: 'unavailable', cited: true, passage_truncated: null, support: 'not_verified', document_id: null, chunk_id: null, filename: null, chunk_index: null, page: null, section: null },
                  ],
                },
              ],
            },
          }
        }
        return { status: 200, body: {} }
      },
    })
    renderPage(CONV)

    const sources = await screen.findByLabelText('Sources')
    expect(sources).toHaveTextContent('[S1] Policy.pdf · page 4')
    expect(sources).toHaveTextContent('[S2] Source no longer available')
    expect(screen.getByText('Retrieved sources — support not verified.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'View source S1' }))
    expect(await screen.findByText('The limit is 500 per trip.')).toBeInTheDocument()
  })

  it('an old conversation without saved citations shows no sources and no buttons', async () => {
    const CONV = 'conv-old'
    installStreamingFetch({
      others: (url) =>
        url.endsWith(CONV)
          ? {
              status: 200,
              body: {
                id: CONV,
                title: 'Old',
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
                messages: [{ id: 'b', role: 'assistant', content: 'Old answer [S1].', created_at: '2026-01-01T00:00:01Z', citations: [] }],
              },
            }
          : { status: 200, body: {} },
    })
    renderPage(CONV)

    expect(await screen.findByText('Old answer [S1].')).toBeInTheDocument()
    expect(screen.queryByLabelText('Sources')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /open source/i })).not.toBeInTheDocument()
  })
})
