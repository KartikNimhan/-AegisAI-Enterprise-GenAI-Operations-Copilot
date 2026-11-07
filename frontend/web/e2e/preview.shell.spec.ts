/**
 * M10.2 in a real browser (preview mode, mock data): the navigation drawer below 768 px. Closed, it
 * is out of view and out of the tab order. Open, it passes axe, everything behind it is inert for
 * the keyboard and for assistive technology, and focus stays inside it. Closing returns focus
 * sensibly (M10 review findings M3, L8, F2 and F3).
 */
import { expect, test, type Page } from '@playwright/test'
import { axeViolations, openPreview, PREVIEW_PAGES, THEMES } from './support/preview.ts'

const OPERATIONS = PREVIEW_PAGES.find((page) => page.route === '/operations')!

/** Whether focus is inside the drawer. */
async function focusIsInDrawer(page: Page): Promise<boolean> {
  return page.evaluate(() => !!document.activeElement?.closest('#app-navigation'))
}

async function openByKeyboard(page: Page) {
  await page.getByRole('button', { name: 'Open navigation' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('#app-navigation')).toBeVisible()
}

/** The (role, name) pairs Chromium's accessibility tree exposes to assistive technology now
 * (ignored nodes, which includes inert content, are left out). Read through the DevTools
 * protocol of the local browser; nothing leaves the machine. */
async function exposedNodes(page: Page): Promise<{ role: string; name: string }[]> {
  const cdp = await page.context().newCDPSession(page)
  try {
    const { nodes } = (await cdp.send('Accessibility.getFullAXTree')) as {
      nodes: { ignored: boolean; role?: { value?: string }; name?: { value?: string } }[]
    }
    return nodes
      .filter((node) => !node.ignored)
      .map((node) => ({ role: String(node.role?.value ?? ''), name: String(node.name?.value ?? '') }))
  } finally {
    await cdp.detach()
  }
}

const has = (nodes: { role: string; name: string }[], role: string, name?: string) =>
  nodes.some((node) => node.role === role && (name === undefined || node.name === name))

for (const theme of THEMES) {
  test.describe(`${theme} theme, 375 px, navigation drawer`, () => {
    test.use({ colorScheme: theme, viewport: { width: 375, height: 900 } })

    test('opens by keyboard, passes axe, and Escape returns focus to the Menu button', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      const drawer = page.locator('#app-navigation')
      await expect(drawer).toBeHidden()

      // Closed, no navigation link is a tab stop: Tab goes skip link -> Menu button.
      await page.keyboard.press('Tab')
      await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
      await page.keyboard.press('Tab')
      const menu = page.getByRole('button', { name: 'Open navigation' })
      await expect(menu).toBeFocused()

      await page.keyboard.press('Enter')
      await expect(drawer).toBeVisible()
      await expect(page.locator('#app-menu-button')).toHaveAttribute('aria-expanded', 'true')
      await expect(drawer.getByRole('button', { name: 'Close navigation' })).toBeVisible()
      await expect(drawer.getByRole('link', { name: 'Copilot' })).toBeFocused()

      const violations = await axeViolations(page)
      expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])

      await page.keyboard.press('Escape')
      await expect(drawer).toBeHidden()
      await expect(page.getByRole('button', { name: 'Open navigation' })).toBeFocused()
    })

    test('assistive technology reaches only the drawer while it is open (F3)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      const before = await exposedNodes(page)
      // Closed: the top bar, its controls and the page content are exposed.
      expect(has(before, 'banner')).toBe(true)
      expect(has(before, 'main')).toBe(true)
      expect(has(before, 'button', 'Open navigation')).toBe(true)
      expect(has(before, 'radio', 'Dark')).toBe(true)

      await openByKeyboard(page)
      const open = await exposedNodes(page)
      // Open: nothing behind the drawer is exposed, not even the top bar ...
      expect(has(open, 'banner')).toBe(false)
      expect(has(open, 'main')).toBe(false)
      expect(has(open, 'heading', 'Operations')).toBe(false)
      expect(has(open, 'button', 'Open navigation')).toBe(false)
      expect(has(open, 'radio', 'Dark')).toBe(false)
      expect(has(open, 'link', 'Skip to main content')).toBe(false)
      // ... and the drawer and its Close control are.
      expect(has(open, 'navigation', 'Main')).toBe(true)
      expect(has(open, 'link', 'Copilot')).toBe(true)
      expect(has(open, 'button', 'Close navigation')).toBe(true)

      await page.keyboard.press('Escape')
      const after = await exposedNodes(page)
      expect(has(after, 'banner')).toBe(true)
      expect(has(after, 'main')).toBe(true)
      expect(has(after, 'button', 'Open navigation')).toBe(true)
    })

    test('Tab and Shift+Tab never leave the open drawer (M3)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      await openByKeyboard(page)

      for (const key of ['Tab', 'Shift+Tab']) {
        for (let step = 0; step < 16; step++) {
          await page.keyboard.press(key)
          expect(await focusIsInDrawer(page), `${key} step ${step}`).toBe(true)
        }
      }

      // From the first link, Shift+Tab goes to the drawer's Close button, and Tab comes back.
      const drawer = page.locator('#app-navigation')
      const first = drawer.getByRole('link', { name: 'Copilot' })
      await first.focus()
      await page.keyboard.press('Shift+Tab')
      await expect(drawer.getByRole('button', { name: 'Close navigation' })).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(first).toBeFocused()
    })

    test('following a link closes the drawer and moves focus to the new page content (M3)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      await openByKeyboard(page)
      await page.locator('#app-navigation').getByRole('link', { name: 'Memory' }).focus()
      await page.keyboard.press('Enter')

      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Memory')
      await expect(page.locator('#app-navigation')).toBeHidden()
      const main = page.getByRole('main')
      await expect(main).toBeFocused()
      await expect(page.locator('[inert]')).toHaveCount(0)
      // The next Tab continues inside the page content.
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => !!document.activeElement?.closest('main'))).toBe(true)
    })

    test('the backdrop and the Close button return focus to the Menu button (M3)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      const drawer = page.locator('#app-navigation')
      const menu = page.getByRole('button', { name: 'Open navigation' })

      await menu.click()
      await expect(drawer).toBeVisible()
      await page.mouse.click(360, 450) // on the backdrop, to the right of the drawer
      await expect(drawer).toBeHidden()
      await expect(menu).toBeFocused()

      await menu.click()
      await drawer.getByRole('button', { name: 'Close navigation' }).click()
      await expect(drawer).toBeHidden()
      await expect(menu).toBeFocused()
      await expect(page.locator('[inert]')).toHaveCount(0)
    })

    test('widening with focus on the Close button moves focus to the current page link (F2)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      await openByKeyboard(page)
      await page.locator('#app-navigation').getByRole('button', { name: 'Close navigation' }).focus()

      await page.setViewportSize({ width: 1280, height: 900 })

      const current = page.locator('#app-navigation').getByRole('link', { name: 'Operations' })
      await expect(current).toHaveAttribute('aria-current', 'page')
      await expect(current).toBeFocused()
      await expect(current).toBeVisible()
      await expect(page.locator('#app-menu-button')).toHaveAttribute('aria-expanded', 'false')
      await expect(page.locator('[inert]')).toHaveCount(0)
      // Nothing focused is hidden: the Menu button and the drawer's Close button are not focused.
      await expect(page.locator('#app-menu-button')).not.toBeFocused()
    })

    test('widening with focus on a link keeps it there, and Escape does nothing afterwards (L8)', async ({ page }) => {
      await openPreview(page, OPERATIONS)
      await openByKeyboard(page)
      const link = page.locator('#app-navigation').getByRole('link', { name: 'Memory' })
      await link.focus()

      await page.setViewportSize({ width: 1280, height: 900 })
      await expect(page.locator('[inert]')).toHaveCount(0)
      await expect(page.locator('#app-menu-button')).toHaveAttribute('aria-expanded', 'false')
      await expect(link).toBeFocused()
      await page.keyboard.press('Escape')
      await expect(link).toBeFocused()

      // Narrow again: the drawer stays closed.
      await page.setViewportSize({ width: 375, height: 900 })
      await expect(page.locator('#app-navigation')).toBeHidden()
    })
  })
}
