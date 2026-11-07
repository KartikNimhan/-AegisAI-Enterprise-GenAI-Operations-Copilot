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
        // Fixed in M10.2: at 375 px Conversations titles and Memory notes were squeezed to 0 px by
        // the fixed 240 px sidebar; with the drawer every page's content is visible at every width.
        expect(hidden).toEqual([])
      })

      test('every page is reachable from the navigation', async ({ page }) => {
        await openPreview(page, COPILOT)
        const nav = page.getByRole('navigation')
        for (const target of PREVIEW_PAGES) {
          // Below 768 px the navigation is a drawer behind the Menu button (M10.2); it is hidden
          // until opened, and following a link closes it again.
          if (width < 768) {
            await expect(nav).toBeHidden()
            await page.getByRole('button', { name: 'Open navigation' }).click()
          }
          await nav.getByRole('link', { name: target.title }).click()
          await expect(page.getByRole('heading', { level: 1 })).toHaveText(target.title)
        }
      })

      test('width of the main content area', async ({ page }) => {
        await openPreview(page, COPILOT)
        const box = await page.getByRole('main').boundingBox()
        if (!box) throw new Error('<main> has no layout box')
        // Fixed in M10.2: below 768 px the sidebar is a drawer, so the content gets the full width
        // (it was 135 px at 375 px). At least 320 px at every width.
        expect(box.width).toBeGreaterThanOrEqual(320)
        if (width < 768) expect(box.width).toBe(width)
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

    test('every tab stop on the Copilot page shows a focus indicator', async ({ page }) => {
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
      // Fixed in M10.1: the message box no longer removes its outline. Any element without a focus
      // indicator fails. This checks that an indicator EXISTS, not its contrast (the token test
      // covers the ring colour).
      expect(seen.has('textarea:Message')).toBe(true)
      expect(missing).toEqual([])
    })

    test('the first tab stop is a skip link that appears on focus and moves focus to <main>', async ({ page }) => {
      await openPreview(page, COPILOT)
      // Fixed in M10.2 (WCAG 2.4.1): the skip link comes first, is visible while focused, and
      // Enter moves focus to the main content.
      await page.keyboard.press('Tab')
      const skip = page.getByRole('link', { name: 'Skip to main content' })
      await expect(skip).toBeFocused()
      await expect(skip).toBeInViewport()
      await page.keyboard.press('Enter')
      await expect(page.getByRole('main')).toBeFocused()
      // The next Tab continues inside the main content, not back in the navigation.
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => !!document.activeElement?.closest('main'))).toBe(true)
    })
  })

  test.describe(`${theme} theme, reduced motion`, () => {
    test.use({ colorScheme: theme, reducedMotion: 'reduce', viewport: { width: 1280, height: 900 } })

    test('the sidebar does not animate its width under reduced motion', async ({ page }) => {
      await openPreview(page, COPILOT)
      expect(await reducedMotionIsEmulated(page)).toBe(true)
      // Fixed in M10.1 (index.css): every transition finishes immediately under reduced motion.
      const duration = await page.locator('aside').evaluate((el) => getComputedStyle(el).transitionDuration)
      expect(parseFloat(duration)).toBeLessThan(0.001)
    })

    test('the streaming cursor does not blink under reduced motion', async ({ page }) => {
      await openPreview(page, COPILOT)
      expect(await reducedMotionIsEmulated(page)).toBe(true)
      // The cursor exists only while the answer streams (a few hundred ms in preview mode). Finding
      // it and then reading its style in a second round trip raced the end of the stream (NaN or a
      // timeout when it had already gone). So its style is read inside the browser, in the same
      // task that adds it to the page, by an observer installed before the message is sent.
      await page.evaluate(() => {
        const win = window as unknown as { __cursorAnimation?: unknown }
        const isCursor = (node: Node): node is HTMLElement =>
          node instanceof HTMLElement && /(^|\s|_)cursor/.test(node.className)
        const record = (el: HTMLElement) => {
          const style = getComputedStyle(el)
          win.__cursorAnimation = {
            name: style.animationName,
            duration: style.animationDuration,
            count: style.animationIterationCount,
          }
          observer.disconnect()
        }
        const observer = new MutationObserver((mutations) => {
          for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
              const found = isCursor(node)
                ? node
                : node instanceof HTMLElement
                  ? node.querySelector<HTMLElement>('[class*="cursor"]')
                  : null
              if (found) return record(found)
            }
          }
        })
        observer.observe(document.body, { childList: true, subtree: true })
      })
      await page.getByRole('textbox', { name: 'Message' }).fill('What can I expense on a trip?')
      await page.getByRole('button', { name: 'Send message' }).click()
      // The cursor must actually appear (a missing cursor fails here, it is not a "known" result).
      const handle = await page.waitForFunction(
        () => (window as unknown as { __cursorAnimation?: unknown }).__cursorAnimation,
      )
      const animation = (await handle.jsonValue()) as { name: string; duration: string; count: string }
      // Fixed in M10.1 (index.css): the blink animation still exists but runs once, for 0.01 ms, so
      // the cursor stays still instead of blinking.
      expect(animation.name).toMatch(/blink/)
      expect(parseFloat(animation.duration)).toBeLessThan(0.001)
      expect(animation.count).toBe('1')
    })
  })
}
