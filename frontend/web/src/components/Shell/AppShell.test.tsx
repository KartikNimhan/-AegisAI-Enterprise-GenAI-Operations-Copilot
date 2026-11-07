/** M10.2: the skip link, the navigation drawer and the Overview's handling of missing data. */
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { previewReply } from '../../preview/mockApi'
import { installFetchMock } from '../../test/mockFetch'
import { ADMIN_ACCOUNT, MEMBER_ACCOUNT, renderApp } from '../../test/renderApp'

afterEach(() => vi.unstubAllGlobals())

function mockBackend(override?: (url: string) => { status: number; body: unknown } | null) {
  installFetchMock((url, init) => {
    const custom = override?.(url)
    if (custom) return custom
    const reply = previewReply(init?.method ?? 'GET', url)
    return { status: reply.status, body: reply.body ?? {} }
  })
}

describe('Skip link', () => {
  it('is the first tab stop and moves focus to the main content', async () => {
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')

    await userEvent.tab()
    const skip = screen.getByRole('link', { name: 'Skip to main content' })
    expect(skip).toHaveFocus()
    expect(skip).toHaveAttribute('href', '#main-content')
    const main = screen.getByRole('main')
    expect(main).toHaveAttribute('id', 'main-content')
    expect(main).toHaveAttribute('tabindex', '-1')
  })
})

// jsdom applies the CSS module but not its media queries, so the Menu button (shown only below
// 768 px) is display:none here and has no computed name; it is found by its label. The real
// narrow-width behaviour is checked in Playwright.
describe('Navigation drawer', () => {
  function drawerElement(): HTMLElement {
    return document.getElementById('app-navigation') as HTMLElement
  }

  function closeButton(): HTMLElement {
    return within(drawerElement()).getByRole('button', { name: 'Close navigation' })
  }

  /** Stubs `matchMedia` so a test can fire the desktop-width change by hand. */
  function stubMatchMedia() {
    const listeners = new Set<(event: MediaQueryListEvent) => void>()
    const removed = vi.fn()
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: false,
        addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
        removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          removed()
          listeners.delete(listener)
        },
      })),
    )
    const widen = () => act(() => listeners.forEach((listener) => listener({ matches: true } as MediaQueryListEvent)))
    return { listeners, removed, widen }
  }

  it('opens from the Menu button, focuses the first link, and Escape returns focus', async () => {
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')

    const menu = screen.getByLabelText('Open navigation')
    expect(menu).toHaveAttribute('aria-expanded', 'false')
    expect(menu).toHaveAttribute('aria-controls', 'app-navigation')
    expect(drawerElement()).toContainElement(screen.getByRole('navigation'))
    expect(within(drawerElement()).queryByRole('button', { name: 'Close navigation' })).not.toBeInTheDocument()

    await userEvent.click(menu)
    expect(menu).toHaveAttribute('aria-expanded', 'true')
    expect(closeButton()).toBeInTheDocument()
    expect(within(screen.getByRole('navigation')).getByRole('link', { name: 'Copilot' })).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    expect(menu).toHaveAttribute('aria-expanded', 'false')
    expect(menu).toHaveFocus()
  })

  it('makes everything behind the open drawer inert, in two sibling regions only (F3)', async () => {
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')
    const banner = screen.getByRole('banner')
    const main = screen.getByRole('main')
    const skip = screen.getByRole('link', { name: 'Skip to main content' })
    expect(document.querySelectorAll('[inert]')).toHaveLength(0)

    await userEvent.click(screen.getByLabelText('Open navigation'))

    const inert = Array.from(document.querySelectorAll('[inert]'))
    expect(inert).toHaveLength(2)
    // No inert region sits inside another, and none contains the drawer.
    for (const region of inert) {
      expect(inert.filter((other) => other !== region && other.contains(region))).toEqual([])
      expect(region.contains(drawerElement())).toBe(false)
    }
    expect(inert).toContain(skip)
    const behind = inert.find((region) => region !== skip) as HTMLElement
    expect(behind).toContainElement(banner) // the top bar, with the Menu button and the theme switch
    expect(behind).toContainElement(main)
    expect(behind).toContainElement(screen.getByLabelText('Open navigation'))
    // The drawer and its Close button stay reachable.
    expect(drawerElement().closest('[inert]')).toBeNull()
    expect(closeButton().closest('[inert]')).toBeNull()
  })

  it.each([
    ['Escape', async () => userEvent.keyboard('{Escape}')],
    ['the backdrop', async () => userEvent.click(document.querySelector<HTMLElement>('[class*="backdrop"]')!)],
    ["the drawer's Close button", async () => userEvent.click(closeButton())],
  ])('closing with %s lifts every inert region and returns focus to the Menu button', async (_how, close) => {
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')
    await userEvent.click(screen.getByLabelText('Open navigation'))

    await close()

    const menu = screen.getByLabelText('Open navigation')
    expect(menu).toHaveAttribute('aria-expanded', 'false')
    expect(menu).toHaveFocus()
    expect(document.querySelectorAll('[inert]')).toHaveLength(0)
    expect(within(drawerElement()).queryByRole('button', { name: 'Close navigation' })).not.toBeInTheDocument()
  })

  it('keeps Tab and Shift+Tab inside the open drawer (M3)', async () => {
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')
    await userEvent.click(screen.getByLabelText('Open navigation'))
    const drawer = drawerElement()
    const close = closeButton()
    const first = within(drawer).getByRole('link', { name: 'Copilot' })
    expect(first).toHaveFocus()

    const visited: Element[] = []
    for (let step = 0; step < 14; step++) {
      await userEvent.tab()
      visited.push(document.activeElement as Element)
    }
    expect(visited.every((el) => drawer.contains(el))).toBe(true)
    expect(visited).toContain(close)
    expect(visited).toContain(first) // it wrapped around

    first.focus()
    await userEvent.tab({ shift: true })
    expect(close).toHaveFocus() // the Close button comes before the links
    await userEvent.tab()
    expect(first).toHaveFocus()
  })

  it('moves focus to the main content after following a drawer link (M3)', async () => {
    mockBackend()
    renderApp('/operations')
    await userEvent.click(screen.getByLabelText('Open navigation'))
    await userEvent.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Memory' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Memory' })).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveFocus()
    expect(screen.getByLabelText('Open navigation')).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelectorAll('[inert]')).toHaveLength(0)
  })

  it('widening with focus on the Close button moves focus to the current page link (F2, L8)', async () => {
    const media = stubMatchMedia()
    mockBackend()
    renderApp('/operations')
    await screen.findByText('Total documents')
    await userEvent.click(screen.getByLabelText('Open navigation'))
    closeButton().focus()
    expect(media.listeners.size).toBe(1)

    media.widen()

    const current = within(screen.getByRole('navigation')).getByRole('link', { name: 'Operations' })
    expect(current).toHaveAttribute('aria-current', 'page')
    expect(current).toHaveFocus()
    expect(screen.getByLabelText('Open navigation')).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelectorAll('[inert]')).toHaveLength(0)
    expect(media.removed).toHaveBeenCalled()
    expect(media.listeners.size).toBe(0)

    // The Escape handler went with it.
    await userEvent.keyboard('{Escape}')
    expect(current).toHaveFocus()
  })

  it('widening with focus on a navigation link leaves focus there (F2)', async () => {
    const media = stubMatchMedia()
    mockBackend()
    renderApp('/operations')
    await userEvent.click(screen.getByLabelText('Open navigation'))
    const memory = within(screen.getByRole('navigation')).getByRole('link', { name: 'Memory' })
    memory.focus()

    media.widen()

    expect(memory).toHaveFocus()
  })

  it('lists Overview, and marks only the Copilot link current on the Copilot page', async () => {
    mockBackend()
    renderApp('/')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/overview')
    expect(within(nav).getAllByRole('link', { current: 'page' })).toHaveLength(1)
  })
})

describe('Overview', () => {
  it('shows real counts and recent conversations from the backend', async () => {
    mockBackend()
    renderApp('/overview')
    expect(await screen.findByText('[MOCK] What can I expense on a trip?')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Documents' })).toBeInTheDocument()
    expect(screen.getByText(/No usage, cost or quality metrics are shown/)).toBeInTheDocument()
  })

  it('shows data that failed to load as unavailable, never as zero', async () => {
    mockBackend((url) => (url.includes('/operations/summary') ? { status: 500, body: { detail: 'down' } } : null))
    renderApp('/overview')

    const documents = screen.getByRole('heading', { name: 'Documents' }).parentElement!
    await waitFor(() => expect(documents).toHaveTextContent('Unavailable'))
    expect(within(documents).queryByText('0')).not.toBeInTheDocument()
  })

  it('shows a zero count as zero when the backend says there is nothing', async () => {
    mockBackend((url) =>
      url.includes('/operations/summary')
        ? { status: 200, body: { total_documents: 0, documents_by_status: { uploaded: 0 } } }
        : null,
    )
    renderApp('/overview')

    const documents = screen.getByRole('heading', { name: 'Documents' }).parentElement!
    await waitFor(() => expect(documents).toHaveTextContent('0documents'))
    expect(documents).not.toHaveTextContent('Unavailable')
  })

  it('shows system checks to administrators only', async () => {
    mockBackend()
    renderApp('/overview', MEMBER_ACCOUNT)
    await screen.findByText('[MOCK] What can I expense on a trip?')
    expect(screen.queryByText('Database')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'System status' })).not.toBeInTheDocument()
  })

  it('shows the database and Redis checks to administrators', async () => {
    mockBackend()
    renderApp('/overview', ADMIN_ACCOUNT)
    expect(await screen.findByText('Database')).toBeInTheDocument()
    expect(screen.getByText('Redis')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'System status' })).toBeInTheDocument()
  })
})
