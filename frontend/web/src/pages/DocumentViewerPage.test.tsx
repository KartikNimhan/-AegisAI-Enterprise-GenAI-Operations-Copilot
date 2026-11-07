/** M10.6: the document viewer (details, extracted text by page, the cited passage, download). */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { expectAxe } from '../test/axe'
import { DocumentViewerPage } from './DocumentViewerPage'

const DOC_ID = '00000000-0000-4000-8000-000000000001'
const DOCUMENT = {
  id: DOC_ID,
  filename: 'Travel policy.pdf',
  content_type: 'application/pdf',
  document_type: 'pdf',
  file_size: 2048,
  status: 'processed',
  error_message: null,
  page_count: 2,
  character_count: 100,
  metadata: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  processed_at: '2026-01-01T00:00:00Z',
}

function chunk(index: number, page: number | null, content = `Passage text ${index}.`) {
  return {
    id: `chunk-${index}`,
    chunk_index: index,
    content,
    character_count: content.length,
    token_count: null,
    metadata: (page === null ? null : { page_number: page }) as Record<string, unknown> | null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

interface Reply {
  status: number
  body?: unknown
  blob?: Blob
}

let requests: string[]

function stubFetch(route: (url: URL) => Reply) {
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(typeof input === 'string' ? input : input.toString(), 'http://test.invalid')
      requests.push(`${url.pathname}${url.search} auth=${new Headers(init?.headers).has('Authorization')}`)
      const reply = route(url)
      return {
        status: reply.status,
        ok: reply.status >= 200 && reply.status < 300,
        json: async () => reply.body,
        text: async () => JSON.stringify(reply.body ?? {}),
        blob: async () => reply.blob ?? new Blob([]),
      } as unknown as Response
    }),
  )
}

function standardBackend(chunks = [chunk(0, 1), chunk(1, 1), chunk(2, 2)]) {
  stubFetch((url) => {
    if (url.pathname === `/api/v1/documents/${DOC_ID}`) return { status: 200, body: DOCUMENT }
    if (url.pathname === `/api/v1/documents/${DOC_ID}/chunks`) {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 10)
      return { status: 200, body: { items: chunks.slice(offset, offset + limit), total: chunks.length } }
    }
    if (url.pathname === `/api/v1/documents/${DOC_ID}/file`) {
      return { status: 200, blob: new Blob(['%PDF-1.4'], { type: 'application/pdf' }) }
    }
    return { status: 404, body: { error: { code: 'not_found', message: 'Not found' } } }
  })
}

function renderViewer(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentViewerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => vi.unstubAllGlobals())

describe('DocumentViewerPage', () => {
  it('shows the details and the extracted text grouped by page, and passes axe', async () => {
    standardBackend()
    const { container } = renderViewer(`/documents/${DOC_ID}`)

    expect(await screen.findByRole('heading', { name: 'Travel policy.pdf' })).toBeInTheDocument()
    const page1 = screen.getByRole('region', { name: 'Page 1' })
    expect(within(page1).getAllByRole('article')).toHaveLength(2)
    expect(within(screen.getByRole('region', { name: 'Page 2' })).getByText('Passage text 2.')).toBeInTheDocument()
    expect(screen.getByText(/This is the text extracted for search/)).toBeInTheDocument()
    await expectAxe(container)
  })

  it('highlights and focuses the passage named by ?chunk=', async () => {
    standardBackend()
    renderViewer(`/documents/${DOC_ID}?chunk=1`)

    const cited = await screen.findByRole('article', { name: 'Passage 2, the cited passage' })
    expect(cited).toHaveAttribute('aria-current', 'location')
    expect(within(cited).getByText('Cited passage')).toBeInTheDocument()
    await waitFor(() => expect(cited).toHaveFocus())
    expect(screen.getAllByRole('article').filter((a) => a.getAttribute('aria-current'))).toHaveLength(1)
  })

  it('loads further pages only as far as the requested passage', async () => {
    const many = Array.from({ length: 450 }, (_, i) => chunk(i, null))
    standardBackend(many)
    renderViewer(`/documents/${DOC_ID}?chunk=250`)

    expect(await screen.findByRole('article', { name: 'Passage 251, the cited passage' })).toBeInTheDocument()
    const chunkRequests = requests.filter((r) => r.includes('/chunks'))
    expect(chunkRequests).toHaveLength(2)
    expect(chunkRequests[1]).toContain('offset=200')
    expect(screen.getByRole('button', { name: 'Load more passages (400 of 450)' })).toBeInTheDocument()
  })

  it.each([450, 99999])(
    'a passage index at or beyond the end (%i of 450) loads only the first page (L9)',
    async (target) => {
      const many = Array.from({ length: 450 }, (_, i) => chunk(i, null))
      standardBackend(many)
      renderViewer(`/documents/${DOC_ID}?chunk=${target}`)

      expect(
        await screen.findByText('The passage you followed is no longer part of this document.'),
      ).toBeInTheDocument()
      const chunkRequests = requests.filter((r) => r.includes('/chunks'))
      expect(chunkRequests).toHaveLength(1)
      expect(chunkRequests[0]).toContain('offset=0')
      expect(screen.getAllByRole('article')).toHaveLength(200)
      expect(screen.getByRole('button', { name: 'Load more passages (200 of 450)' })).toBeInTheDocument()
    },
  )

  it('the last real passage is still loaded when it is beyond the first page (L9)', async () => {
    const many = Array.from({ length: 450 }, (_, i) => chunk(i, null))
    standardBackend(many)
    renderViewer(`/documents/${DOC_ID}?chunk=449`)

    expect(await screen.findByRole('article', { name: 'Passage 450, the cited passage' })).toBeInTheDocument()
    expect(requests.filter((r) => r.includes('/chunks'))).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /Load more passages/ })).not.toBeInTheDocument()
  })

  it('shows the section a passage falls under, when the backend recorded one (M10.9)', async () => {
    standardBackend([
      { ...chunk(0, null), metadata: { section: 'Hotels' } },
      { ...chunk(1, null), metadata: { section: 42 } },
      chunk(2, null),
    ])
    renderViewer(`/documents/${DOC_ID}`)
    const articles = await screen.findAllByRole('article')
    expect(articles[0]).toHaveTextContent('Passage 1· Hotels')
    expect(articles[1]).not.toHaveTextContent('·')
    expect(articles[2]).not.toHaveTextContent('·')
  })

  it('says when the followed passage no longer exists', async () => {
    standardBackend()
    renderViewer(`/documents/${DOC_ID}?chunk=99`)
    expect(await screen.findByText('The passage you followed is no longer part of this document.')).toBeInTheDocument()
  })

  it('ignores a malformed ?chunk= value', async () => {
    standardBackend()
    renderViewer(`/documents/${DOC_ID}?chunk=-1`)
    await screen.findByRole('heading', { name: 'Travel policy.pdf' })
    expect(screen.queryByText(/Cited passage/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([404, 403])('shows nothing about a document answered with %i', async (status) => {
    stubFetch(() => ({ status, body: { error: { code: 'not_found', message: 'Document not found' } } }))
    renderViewer(`/documents/${DOC_ID}?chunk=0`)

    expect(await screen.findByRole('heading', { name: 'Document not available' })).toBeInTheDocument()
    expect(screen.queryByText(/Travel policy/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument()
  })

  it('offers a retry for other errors', async () => {
    stubFetch(() => ({ status: 500, body: { error: { code: 'internal', message: 'Something broke' } } }))
    renderViewer(`/documents/${DOC_ID}`)
    expect(await screen.findByRole('button', { name: /try again|retry/i })).toBeInTheDocument()
  })

  it('downloads the original through an authenticated request, as a file', async () => {
    standardBackend()
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL }))
    const clicked: { href: string; download: string }[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, download: this.download })
    })

    renderViewer(`/documents/${DOC_ID}`)
    await userEvent.click(await screen.findByRole('button', { name: 'Download original' }))

    await waitFor(() => expect(clicked).toHaveLength(1))
    expect(clicked[0]).toEqual({ href: 'blob:test', download: 'Travel policy.pdf' })
    expect(requests.some((r) => r.startsWith(`/api/v1/documents/${DOC_ID}/file`))).toBe(true)
    click.mockRestore()
  })

  it('reports an unavailable original without breaking the page', async () => {
    stubFetch((url) => {
      if (url.pathname === `/api/v1/documents/${DOC_ID}`) return { status: 200, body: DOCUMENT }
      if (url.pathname.endsWith('/chunks')) return { status: 200, body: { items: [chunk(0, 1)], total: 1 } }
      return { status: 404, body: { error: { code: 'not_found', message: 'Document not found' } } }
    })
    renderViewer(`/documents/${DOC_ID}`)
    await userEvent.click(await screen.findByRole('button', { name: 'Download original' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The original file is not available.')
    expect(screen.getByText('Passage text 0.')).toBeInTheDocument()
  })
})
