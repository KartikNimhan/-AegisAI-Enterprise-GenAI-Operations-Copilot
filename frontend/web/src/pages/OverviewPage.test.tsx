/**
 * M10 review finding M2: the Overview tells failed, malformed and genuinely empty answers apart,
 * and never shows missing data as zero (M10 decision 11).
 */
import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ADMIN_ACCOUNT, renderApp } from '../test/renderApp'

type Reply = { status: number; text: string }

const json = (body: unknown): Reply => ({ status: 200, text: JSON.stringify(body) })
const VALID: Record<string, Reply> = {
  '/api/v1/operations/summary': json({ total_documents: 3, documents_by_status: { processed: 3 } }),
  '/api/v1/conversations': json([
    { id: 'c1', title: 'Travel question', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' },
  ]),
  '/api/v1/memories': json([{ id: 'm1' }, { id: 'm2' }]),
  '/api/v1/system/status': json({ database: 'ok', redis: 'ok', llm_configured: true, trusted_a2a_agents: [], mcp_server: '' }),
}

/** Answers every Overview endpoint as `VALID`, except the ones in `overrides`. */
function stubBackend(overrides: Record<string, Reply> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request) => {
      const path = new URL(typeof input === 'string' ? input : input.toString(), 'http://test.invalid').pathname
      const reply = path === '/health' ? json({ status: 'ok' }) : (overrides[path] ?? VALID[path] ?? { status: 404, text: '{}' })
      return {
        status: reply.status,
        ok: reply.status >= 200 && reply.status < 300,
        text: async () => reply.text,
        json: async () => JSON.parse(reply.text),
      } as unknown as Response
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

function card(name: string): HTMLElement {
  return screen.getByRole('heading', { name }).parentElement as HTMLElement
}

const ALL = ['/api/v1/operations/summary', '/api/v1/conversations', '/api/v1/memories', '/api/v1/system/status']
const everywhere = (reply: Reply) => Object.fromEntries(ALL.map((path) => [path, reply]))

const MALFORMED = 'Unavailable: the backend answered without usable data.'
const FAILED = 'Unavailable: the request to the backend failed.'

describe('Overview data states', () => {
  it.each([
    ['an empty 200 body', { status: 200, text: '' }, MALFORMED],
    ['a 204 No Content', { status: 204, text: '' }, MALFORMED],
    ['a malformed {} body', { status: 200, text: '{}' }, MALFORMED],
    ['a 200 body that is not JSON', { status: 200, text: '<html>proxy page</html>' }, MALFORMED],
    ['a 201 body cut off mid-JSON', { status: 201, text: '{"total_documents": 3, "docu' }, MALFORMED],
    ['HTTP 500', { status: 500, text: JSON.stringify({ error: { code: 'internal', message: 'boom' } }) }, FAILED],
    ['HTTP 502 with a body that is not JSON', { status: 502, text: '<html>Bad gateway</html>' }, FAILED],
  ])('%s is shown as unavailable on every card, never as zero', async (_case, reply, message) => {
    stubBackend(everywhere(reply))
    renderApp('/overview', ADMIN_ACCOUNT)

    for (const name of ['Documents', 'Recent conversations', 'Memory']) {
      expect(await within(card(name)).findByText(message)).toBeInTheDocument()
      expect(card(name)).not.toHaveTextContent(/\b0\b/)
    }
    expect(within(card('Recent conversations')).queryByText('No conversations yet.')).not.toBeInTheDocument()
    expect(await within(card('Service')).findByText(message)).toBeInTheDocument()
    expect(within(card('Service')).queryByText('Database')).not.toBeInTheDocument()
  })

  it.each([
    ['a negative count', { total_documents: -1, documents_by_status: {} }],
    ['a count given as text', { total_documents: '3', documents_by_status: {} }],
    ['a missing breakdown', { total_documents: 3 }],
    ['a list instead of an object', [1, 2, 3]],
  ])('a document summary with %s is malformed', async (_case, body) => {
    stubBackend({ '/api/v1/operations/summary': json(body) })
    renderApp('/overview')
    expect(await within(card('Documents')).findByText(MALFORMED)).toBeInTheDocument()
  })

  it('a list of the wrong shape is malformed, not empty', async () => {
    stubBackend({ '/api/v1/conversations': json([{ no: 'id' }]), '/api/v1/memories': json({ items: [] }) })
    renderApp('/overview')
    expect(await within(card('Recent conversations')).findByText(MALFORMED)).toBeInTheDocument()
    expect(await within(card('Memory')).findByText(MALFORMED)).toBeInTheDocument()
  })

  it('real zeros and empty lists are shown as such', async () => {
    stubBackend({
      '/api/v1/operations/summary': json({ total_documents: 0, documents_by_status: { processed: 0 } }),
      '/api/v1/conversations': json([]),
      '/api/v1/memories': json([]),
    })
    renderApp('/overview')

    expect(await within(card('Documents')).findByText('documents')).toBeInTheDocument()
    expect(card('Documents')).toHaveTextContent('0documents')
    expect(await within(card('Recent conversations')).findByText('No conversations yet.')).toBeInTheDocument()
    expect(await within(card('Memory')).findByText('saved notes')).toBeInTheDocument()
    expect(card('Memory')).toHaveTextContent('0saved notes')
    for (const name of ['Documents', 'Recent conversations', 'Memory']) {
      expect(card(name)).not.toHaveTextContent('Unavailable')
    }
  })

  it('valid data is shown', async () => {
    stubBackend()
    renderApp('/overview', ADMIN_ACCOUNT)
    expect(await screen.findByText('Travel question')).toBeInTheDocument()
    expect(card('Documents')).toHaveTextContent('3documents')
    expect(card('Memory')).toHaveTextContent('2saved notes')
    expect(await within(card('Service')).findByText('Database')).toBeInTheDocument()
  })
})
