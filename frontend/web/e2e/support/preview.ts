/**
 * Helpers for the preview project: the real app with mock data (src/preview/*), no network.
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

export interface PreviewPage {
  route: string
  title: string
  /** Text shown once the page's mock data has loaded. */
  ready: string
}

export const PREVIEW_PAGES: PreviewPage[] = [
  { route: '/', title: 'Copilot', ready: 'No messages yet' },
  { route: '/conversations', title: 'Conversations', ready: '[MOCK] What can I expense on a trip?' },
  { route: '/documents', title: 'Documents', ready: '[MOCK] Travel policy.pdf' },
  { route: '/memory', title: 'Memory', ready: '[MOCK] Prefers short answers' },
  { route: '/operations', title: 'Operations', ready: 'Total documents' },
  { route: '/system', title: 'System Status', ready: 'Database (PostgreSQL)' },
]

export const WIDTHS = [375, 768, 1280] as const
export const THEMES = ['light', 'dark'] as const

/**
 * Opens a page in the preview and waits until its mock data is in the page. `visible: false` waits
 * only for the text to be in the DOM (for layout checks that must run even when the text is
 * squeezed out of view, which is itself a finding).
 */
export async function openPreview(page: Page, { route, ready }: PreviewPage, { visible = true } = {}): Promise<void> {
  await page.goto(`/preview.html?route=${encodeURIComponent(route)}`)
  await page.getByText(ready).first().waitFor({ state: visible ? 'visible' : 'attached' })
}

/** WCAG 2.0–2.2 A/AA rules plus axe best practices. The preview banner is not part of the app. */
export async function axeViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
    .exclude('[aria-label="Preview mode"]')
    .analyze()
  return results.violations
}

/** Whether the focused element shows a focus indicator: an outline or a box-shadow. */
export async function focusIndicator(page: Page): Promise<{ tag: string; label: string; visible: boolean }> {
  return page.evaluate(() => {
    const element = document.activeElement as HTMLElement | null
    if (!element || element === document.body) return { tag: 'body', label: '', visible: false }
    const style = getComputedStyle(element)
    const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0
    const shadow = style.boxShadow !== 'none' && style.boxShadow !== ''
    const label = element.getAttribute('aria-label') ?? element.textContent?.trim().slice(0, 40) ?? ''
    return { tag: element.tagName.toLowerCase(), label, visible: outline || shadow }
  })
}
