/**
 * Accessibility checks for component tests (axe-core through jest-axe).
 *
 * jsdom has no layout engine and no canvas, so axe cannot compute colours or sizes here: the
 * `color-contrast` rule is turned off in this helper only. Contrast is checked instead by
 * `src/styles/tokens.contrast.test.ts` (both themes) and by the Playwright suite in a real browser.
 *
 * `expectAxe` compares the violated rule ids with an explicit list of KNOWN issues (empty by
 * default). A new violation fails the test, and so does a known issue that no longer occurs, so
 * the list can only shrink as issues are fixed. Known issues are never hidden: each one is named
 * in the test that expects it, with the milestone that fixes it.
 */
import type { Result } from 'axe-core'
import { configureAxe } from 'jest-axe'
import { expect } from 'vitest'

const runAxe = configureAxe({
  runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
  rules: {
    // Not computable in jsdom (see above).
    'color-contrast': { enabled: false },
  },
})

export interface AxeExpectation {
  /** Rule ids that are known to fail today. Each must actually occur. */
  known?: string[]
  /** `false` for a component rendered on its own, outside the app's landmarks. */
  landmarks?: boolean
}

function formatViolations(violations: Result[]): string {
  return violations
    .map((v) => `${v.id} (${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
    .join('\n')
}

export async function expectAxe(container: Element, expectation: AxeExpectation = {}): Promise<void> {
  const results = await runAxe(container, {
    rules: expectation.landmarks === false ? { region: { enabled: false } } : {},
  })
  const actual = [...new Set(results.violations.map((v) => v.id))].sort()
  const known = [...(expectation.known ?? [])].sort()
  expect(actual, `axe violations:\n${formatViolations(results.violations)}`).toEqual(known)
}
