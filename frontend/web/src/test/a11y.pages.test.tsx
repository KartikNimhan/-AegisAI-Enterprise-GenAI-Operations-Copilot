/**
 * Page-level accessibility tests (M10.0): every route rendered inside the real app shell with the
 * preview's mock backend (no network, no model calls), checked with axe and with explicit
 * assertions about landmarks, headings, names and navigation state.
 *
 * Colour contrast and both themes are covered by `src/styles/tokens.contrast.test.ts` and the
 * Playwright suite (jsdom cannot compute colours; see ./axe.ts).
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Me } from '../api/auth'
import { previewReply } from '../preview/mockApi'
import { expectAxe } from './axe'
import { installFetchMock } from './mockFetch'
import { ADMIN_ACCOUNT, MEMBER_ACCOUNT, renderApp } from './renderApp'

function mockBackend() {
  installFetchMock((url, init) => {
    const reply = previewReply(init?.method ?? 'GET', url)
    return { status: reply.status, body: reply.body ?? {} }
  })
}

interface PageCase {
  path: string
  title: string
  /** Text that appears once the page's data has loaded. */
  ready: string
  account: Me
  /** axe rules known to fail today (see ./axe.ts); each entry names the milestone that fixes it. */
  known?: string[]
}

const PAGES: PageCase[] = [
  { path: '/', title: 'Copilot', ready: 'No messages yet', account: MEMBER_ACCOUNT },
  { path: '/overview', title: 'Overview', ready: '[MOCK] What can I expense on a trip?', account: MEMBER_ACCOUNT },
  { path: '/conversations', title: 'Conversations', ready: '[MOCK] What can I expense on a trip?', account: MEMBER_ACCOUNT },
  {
    path: '/documents',
    title: 'Documents',
    ready: '[MOCK] Travel policy.pdf',
    account: MEMBER_ACCOUNT,
    // Fixed in M10.8: the "Actions" column header now has (visually hidden) text.
  },
  { path: '/memory', title: 'Memory', ready: '[MOCK] Prefers short answers', account: MEMBER_ACCOUNT },
  { path: '/operations', title: 'Operations', ready: 'Total documents', account: MEMBER_ACCOUNT },
  { path: '/system', title: 'System Status', ready: 'Database (PostgreSQL)', account: ADMIN_ACCOUNT },
]

describe.each(PAGES)('$title page ($path)', ({ path, title, ready, account, known }) => {
  it('passes axe once its data has loaded (apart from listed known issues)', async () => {
    mockBackend()
    const { container } = renderApp(path, account)
    expect(await screen.findAllByText(ready)).not.toHaveLength(0)
    await expectAxe(container, { known })
  })

  it('has one page heading, the main and navigation landmarks, and marks the current page', async () => {
    mockBackend()
    renderApp(path, account)
    await screen.findAllByText(ready)

    const headings = screen.getAllByRole('heading', { level: 1 })
    expect(headings).toHaveLength(1)
    expect(headings[0]).toHaveTextContent(title)
    expect(screen.getByRole('main')).toBeInTheDocument()

    const nav = screen.getByRole('navigation')
    const current = within(nav).getByRole('link', { current: 'page' })
    expect(current).toHaveAccessibleName(title)
  })

  it('gives every button and link an accessible name', async () => {
    mockBackend()
    renderApp(path, account)
    await screen.findAllByText(ready)

    for (const control of [...screen.getAllByRole('button'), ...screen.getAllByRole('link')]) {
      expect(control).toHaveAccessibleName()
    }
  })
})

describe('Navigation', () => {
  it('lists System Status for administrators only', async () => {
    mockBackend()
    renderApp('/', MEMBER_ACCOUNT)
    const memberNav = screen.getByRole('navigation')
    expect(within(memberNav).queryByRole('link', { name: 'System Status' })).not.toBeInTheDocument()
  })

  it('keeps accessible link names when the sidebar is collapsed', async () => {
    mockBackend()
    renderApp('/', ADMIN_ACCOUNT)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))

    const nav = screen.getByRole('navigation')
    for (const name of ['Copilot', 'Conversations', 'Documents', 'Memory', 'Operations', 'System Status']) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })
})
