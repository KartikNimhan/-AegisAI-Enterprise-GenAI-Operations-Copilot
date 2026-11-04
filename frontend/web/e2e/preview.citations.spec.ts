/**
 * M10.5 in a real browser (preview mode, mock data): a citation marker opens the source panel from
 * the keyboard, the open panel passes axe, and closing it returns focus to the marker.
 */
import { expect, test } from '@playwright/test'
import { axeViolations, openPreview, PREVIEW_PAGES, THEMES } from './support/preview.ts'

const COPILOT = PREVIEW_PAGES.find((page) => page.route === '/')!

for (const theme of THEMES) {
  test.describe(`${theme} theme, citations`, () => {
    test.use({ colorScheme: theme, viewport: { width: 1280, height: 900 } })

    test('a marker opens the source panel by keyboard, and Escape returns focus to it', async ({ page }) => {
      await openPreview(page, COPILOT)
      await page.getByRole('textbox', { name: 'Message' }).fill('What is the travel policy?')
      await page.getByRole('button', { name: 'Send message' }).click()

      const marker = page.getByRole('button', { name: 'Open source S1' })
      await marker.waitFor()
      await marker.focus()
      await page.keyboard.press('Enter')

      const dialog = page.getByRole('dialog', { name: 'Source S1' })
      await expect(dialog).toBeVisible()
      await expect(dialog).toContainText('Retrieved source — support not verified')
      await expect(dialog).toContainText('[MOCK] Employees may claim economy fares')
      await expect(page.getByRole('button', { name: 'Close' })).toBeFocused()

      const violations = await axeViolations(page)
      expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])

      await page.getByRole('button', { name: 'Show surrounding text' }).click()
      await expect(dialog).toContainText('[MOCK] Hotel stays are reimbursed')

      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(marker).toBeFocused()
    })

    test('the source document link opens the viewer at the cited passage (M10.6)', async ({ page }) => {
      await openPreview(page, COPILOT)
      await page.getByRole('textbox', { name: 'Message' }).fill('What is the travel policy?')
      await page.getByRole('button', { name: 'Send message' }).click()
      await page.getByRole('button', { name: 'Open source S1' }).click()

      await page.getByRole('dialog', { name: 'Source S1' }).getByRole('link', { name: '[MOCK] Travel policy.pdf' }).click()

      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Document')
      const cited = page.getByRole('article', { name: 'Passage 1, the cited passage' })
      await expect(cited).toBeFocused()
      await expect(cited).toContainText('[MOCK] Employees may claim economy fares')
      const violations = await axeViolations(page)
      expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])

      // The preview holds no files: the download says so instead of producing made-up content.
      await page.getByRole('button', { name: 'Download original' }).click()
      await expect(page.getByRole('alert')).toHaveText('The original file is not available.')
    })
  })
}
