/**
 * Responsive layout, keyboard navigation, visible focus and reduced motion (M10.0), in both
 * themes, at 375, 768 and 1280 px.
 *
 * Known gaps are asserted EXPLICITLY at their current, measured values (for example "the sidebar
 * transition is still 0.15s"), each with a comment naming the milestone that fixes it. Fixing a
 * gap therefore makes its test fail until the assertion is updated to the target behaviour, and an
 * unrelated failure (a timeout, a wrong selector, a missing precondition) can never pass as a
 * "known" result. Nothing is skipped and nothing is marked as an expected failure.
 */
import { expect, test, type Page } from '@playwright/test'
import { KNOWN_MAIN_OVERFLOW } from './support/known-issues.ts'
import { focusIndicator, openPreview, PREVIEW_PAGES, THEMES, WIDTHS } from './support/preview.ts'

const COPILOT = PREVIEW_PAGES[0]

async function horizontalOverflow(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector('main')
    if (!main) throw new Error('no <main> element')
    return {
      document: { content: document.documentElement.scrollWidth, visible: window.innerWidth },
      main: { content: main.scrollWidth, visible: main.clientWidth },
    }
  })
}

async function reducedMotionIsEmulated(page: Page): Promise<boolean> {
  return page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    test.describe(`${theme} theme, ${width} px`, () => {
      test.use({ colorScheme: theme, viewport: { width, height: 900 } })

      test('reflow (WCAG 1.4.10): no horizontal overflow of the document or inside <main>, except recorded known issues', async ({ page }) => {
        const documentOverflow: string[] = []
        const mainOverflow: Record<string, string> = {}
        for (const target of PREVIEW_PAGES) {
          await openPreview(page, target, { visible: false })
          const measured = await horizontalOverflow(page)
          if (measured.document.content > measured.document.visible) {
            documentOverflow.push(`${target.route}: ${measured.document.content}px > ${measured.document.visible}px`)
          }
          if (measured.main.content > measured.main.visible) {
            mainOverflow[target.route] = `${measured.main.content}px content in ${measured.main.visible}px`
          }
        }
        // The page as a whole must never scroll horizontally.
        expect(documentOverflow).toEqual([])
        // Inside <main>: exactly the pages recorded in KNOWN_MAIN_OVERFLOW overflow at this width
        // (measured values there; fix M10.2/M10.8). A new overflowing page fails, and so does a
        // fixed one that is still recorded.
        expect(Object.keys(mainOverflow).sort(), `overflow inside <main>: ${JSON.stringify(mainOverflow)}`).toEqual(
          Object.keys(KNOWN_MAIN_OVERFLOW[width]).sort(),
        )
      })

      test("each page's main content is visible", async ({ page }) => {
        const hidden: string[] = []
        for (const target of PREVIEW_PAGES) {
          await openPreview(page, target, { visible: false })
          if (!(await page.getByText(target.ready).first().isVisible())) hidden.push(target.route)
        }
        // Known M10.0 gap at 375 px: with the 240 px sidebar the content area is 135 px, and the
        // shared list row (ListPages.module.css) lets its action buttons squeeze the text column to
        // 0 px, so Conversations titles and Memory notes cannot be read. Fix: M10.2 (mobile drawer)
        // and M10.8 (list layout). Any other hidden content fails.
        expect(hidden).toEqual(width === 375 ? ['/conversations', '/memory'] : [])
      })

      test('every page is reachable from the navigation', async ({ page }) => {
        await openPreview(page, COPILOT)
        const nav = page.getByRole('navigation')
        for (const target of PREVIEW_PAGES) {
          await nav.getByRole('link', { name: target.title }).click()
          await expect(page.getByRole('heading', { level: 1 })).toHaveText(target.title)
        }
      })

      test('width of the main content area', async ({ page }) => {
        await openPreview(page, COPILOT)
        const box = await page.getByRole('main').boundingBox()
        if (!box) throw new Error('<main> has no layout box')
        if (width === 375) {
          // Known M10.0 gap: the fixed 240 px sidebar leaves exactly 135 px (375 - 240) for the
          // content, below the 320 px minimum. Fix: M10.2 (mobile drawer); then assert >= 320 here.
          expect(box.width).toBe(135)
        } else {
          expect(box.width).toBeGreaterThanOrEqual(320)
        }
      })
    })
  }

  test.describe(`${theme} theme, keyboard`, () => {
    test.use({ colorScheme: theme, viewport: { width: 1280, height: 900 } })

    test('Tab reaches the navigation and Enter opens a page', async ({ page }) => {
      await openPreview(page, COPILOT)
      const documents = page.getByRole('navigation').getByRole('link', { name: 'Documents' })
      for (let step = 0; step < 20 && !(await documents.evaluate((el) => el === document.activeElement)); step++) {
        await page.keyboard.press('Tab')
      }
      await expect(documents).toBeFocused()
      await page.keyboard.press('Enter')
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Documents')
    })

    test('every tab stop on the Copilot page shows a focus indicator, except the known composer gap', async ({ page }) => {
      await openPreview(page, COPILOT)
      const missing: string[] = []
      const seen = new Set<string>()
      for (let step = 0; step < 25; step++) {
        await page.keyboard.press('Tab')
        const focused = await focusIndicator(page)
        const key = `${focused.tag}:${focused.label}`
        if (focused.tag === 'body' || seen.has(key)) break
        seen.add(key)
        if (!focused.visible) missing.push(key)
      }
      expect(seen.size).toBeGreaterThan(3)
      // Known M10.0 gap: the message box sets `outline: none` with no replacement
      // (Composer.module.css). Fix: M10.1/M10.3. Any other element without a focus indicator fails.
      // This checks that an indicator EXISTS, not its contrast (the token test covers the ring colour).
      expect(missing).toEqual(['textarea:Message'])
    })

    test('first tab stop — known gap: no skip link yet, Tab goes straight to the navigation', async ({ page }) => {
      await openPreview(page, COPILOT)
      // Known M10.0 gap: there is no "skip to main content" link. Fix: M10.2. When it is added,
      // this test fails and must be changed to assert the skip link is the first tab stop.
      await expect(page.getByRole('link', { name: /skip to/i })).toHaveCount(0)
      await page.keyboard.press('Tab')
      await expect(page.getByRole('navigation').getByRole('link', { name: 'Copilot' })).toBeFocused()
    })
  })

  test.describe(`${theme} theme, reduced motion`, () => {
    test.use({ colorScheme: theme, reducedMotion: 'reduce', viewport: { width: 1280, height: 900 } })

    test('known gap: the sidebar still animates its width (0.15s) under reduced motion', async ({ page }) => {
      await openPreview(page, COPILOT)
      expect(await reducedMotionIsEmulated(page)).toBe(true)
      // Known M10.0 gap: the transition ignores prefers-reduced-motion. Fix: M10.1; then assert '0s'.
      const duration = await page.locator('aside').evaluate((el) => getComputedStyle(el).transitionDuration)
      expect(duration).toBe('0.15s')
    })

    test('known gap: the streaming cursor still blinks under reduced motion', async ({ page }) => {
      await openPreview(page, COPILOT)
      expect(await reducedMotionIsEmulated(page)).toBe(true)
      await page.getByRole('textbox', { name: 'Message' }).fill('What can I expense on a trip?')
      await page.getByRole('button', { name: 'Send message' }).click()
      // The cursor must actually appear (a missing cursor fails here, it is not a "known" result).
      const cursor = page.locator('[class*="cursor"]').first()
      await cursor.waitFor()
      // Known M10.0 gap: its `blink` animation ignores prefers-reduced-motion. Fix: M10.1/M10.3;
      // then assert animationName is 'none'. (CSS-module names are hashed, e.g. `_blink_8jjvr_1`.)
      expect(await cursor.evaluate((el) => getComputedStyle(el).animationName)).toMatch(/blink/)
    })
  })
}
