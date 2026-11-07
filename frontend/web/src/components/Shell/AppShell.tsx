import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import styles from './AppShell.module.css'

export const SIDEBAR_ID = 'app-navigation'
const MAIN_ID = 'main-content'
const MENU_ID = 'app-menu-button'
/** From this width up the sidebar sits beside the content; below it, it is a drawer. */
const DESKTOP_QUERY = '(min-width: 768px)'

/** Where focus goes once the drawer has closed (applied after the closing render). */
type FocusTarget = 'menu' | 'main' | 'navigation'

function drawer(): HTMLElement | null {
  return document.getElementById(SIDEBAR_ID)
}

/** The drawer's controls that can take focus right now (hidden ones, such as the collapse toggle
 * in the drawer, are left out). */
function drawerControls(): HTMLElement[] {
  const element = drawer()
  if (!element) return []
  return Array.from(element.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')).filter(
    (control) => getComputedStyle(control).display !== 'none',
  )
}

/** Whether focus sits on something a keyboard user can see and use. */
function focusIsUsable(): boolean {
  const active = document.activeElement
  return (
    active instanceof HTMLElement &&
    active !== document.body &&
    active.isConnected &&
    getComputedStyle(active).display !== 'none'
  )
}

/**
 * The application shell (M10.2; focus handling corrected after the M10 review: M3, L8, F2, F3).
 *
 * - A "Skip to main content" link is the first tab stop (WCAG 2.4.1); `<main>` can take focus.
 * - From 768 px up the sidebar sits beside the content and can be collapsed to icons.
 * - Below 768 px it is a drawer opened from the top bar's Menu button. While it is open:
 *   - everything behind it is `inert`: the skip link and the region holding the top bar and the
 *     page content (two sibling regions, never nested). Keyboard and assistive technology reach
 *     only the drawer, which carries its own Close button (F3);
 *   - focus moves to its first navigation link, and Tab / Shift+Tab cycle through the drawer;
 *   - following a link closes it and moves focus to the main content of the new page;
 *   - Escape, the backdrop or the drawer's Close button close it and return focus to the Menu
 *     button (no longer inert by then);
 *   - widening the window to 768 px or more closes it. If focus would be left on a control that
 *     is now hidden (the drawer's Close button), it moves to the current page's link in the
 *     sidebar, which is visible beside the content (F2). The listeners go with it (L8).
 */
export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const focusAfterClose = useRef<FocusTarget | null>(null)

  function closeDrawer(target: FocusTarget) {
    focusAfterClose.current = target
    setDrawerOpen(false)
  }

  useEffect(() => {
    if (!drawerOpen) {
      const target = focusAfterClose.current
      focusAfterClose.current = null
      if (target === 'menu') document.getElementById(MENU_ID)?.focus()
      if (target === 'main') document.getElementById(MAIN_ID)?.focus()
      if (target === 'navigation' && !focusIsUsable()) {
        const nav = drawer()
        ;(
          nav?.querySelector<HTMLElement>('a[aria-current="page"]') ?? nav?.querySelector<HTMLElement>('a[href]')
        )?.focus()
      }
      return
    }
    drawer()?.querySelector<HTMLElement>('nav a[href]')?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        closeDrawer('menu')
        return
      }
      if (event.key !== 'Tab') return
      // Keep focus inside the drawer (WCAG 2.4.3). The rest of the page is inert anyway; this
      // also stops Tab from leaving the document for the browser's own controls.
      const cycle = drawerControls()
      if (cycle.length === 0) return
      event.preventDefault()
      const index = cycle.indexOf(document.activeElement as HTMLElement)
      const next = event.shiftKey
        ? index <= 0
          ? cycle.length - 1
          : index - 1
        : index === -1 || index === cycle.length - 1
          ? 0
          : index + 1
      cycle[next].focus()
    }

    const desktop = typeof window.matchMedia === 'function' ? window.matchMedia(DESKTOP_QUERY) : null
    function onWidthChange(event: MediaQueryListEvent) {
      if (event.matches) closeDrawer('navigation')
    }

    document.addEventListener('keydown', onKeyDown)
    desktop?.addEventListener('change', onWidthChange)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      desktop?.removeEventListener('change', onWidthChange)
    }
  }, [drawerOpen])

  return (
    <div className={`${styles.shell} ${drawerOpen ? styles.drawerOpen : ''}`}>
      <a href={`#${MAIN_ID}`} className={styles.skipLink} inert={drawerOpen}>
        Skip to main content
      </a>
      <Sidebar
        id={SIDEBAR_ID}
        collapsed={collapsed && !drawerOpen}
        onToggle={() => setCollapsed((c) => !c)}
        className={styles.sidebar}
        onNavigate={() => {
          if (drawerOpen) closeDrawer('main')
        }}
        onCloseDrawer={drawerOpen ? () => closeDrawer('menu') : undefined}
      />
      {drawerOpen && <div className={styles.backdrop} onClick={() => closeDrawer('menu')} aria-hidden="true" />}
      <div className={styles.main} inert={drawerOpen}>
        <Topbar
          title={title}
          menuOpen={drawerOpen}
          onMenu={() => setDrawerOpen(true)}
          menuControls={SIDEBAR_ID}
          menuId={MENU_ID}
        />
        <main id={MAIN_ID} tabIndex={-1} className={styles.content}>
          {children}
        </main>
      </div>
    </div>
  )
}
