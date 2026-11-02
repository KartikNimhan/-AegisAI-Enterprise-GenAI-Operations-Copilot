/**
 * Browser accessibility checks (axe-core in Chromium) on every page, in the light and the dark
 * theme (M10.0).
 *
 * Each page/theme must show exactly the violations recorded in support/known-issues.ts (rule and
 * number of affected elements). A new violation, a new affected element, or a fixed one that is
 * still recorded all fail, so the baseline can only shrink. Rules are never disabled to make this
 * pass: every known issue is listed with the milestone that fixes it.
 */
import { expect, test } from '@playwright/test'
import { KNOWN_ISSUES } from './support/known-issues.ts'
import { axeViolations, openPreview, PREVIEW_PAGES, THEMES } from './support/preview.ts'

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    test.use({ colorScheme: theme, viewport: { width: 1280, height: 900 } })

    for (const page of PREVIEW_PAGES) {
      test(`${page.title}: axe finds only the recorded known issues`, async ({ page: browser }) => {
        await openPreview(browser, page)
        const violations = await axeViolations(browser)
        const actual = Object.fromEntries(violations.map((v) => [v.id, v.nodes.length]))
        const details = violations
          .map((v) => `${v.id} (${v.impact}, ${v.nodes.length} elements): ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).join('\n    ')}`)
          .join('\n')
        expect(actual, `axe violations on ${page.route} (${theme}):\n${details}`).toEqual(
          KNOWN_ISSUES[`${page.route} ${theme}`] ?? {},
        )
      })
    }
  })
}
