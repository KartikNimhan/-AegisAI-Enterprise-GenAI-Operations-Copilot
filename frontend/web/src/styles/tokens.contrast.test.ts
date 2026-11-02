/**
 * Automated WCAG 2.2 AA contrast check of the design tokens, in BOTH themes (M10.0).
 *
 * It reads `tokens.css` itself, resolves `var(--…)` references for the light theme (`:root`) and
 * the dark theme (`[data-theme='dark']`, which must match the `prefers-color-scheme: dark` block),
 * and computes the WCAG contrast ratio of each colour pair the CSS modules actually use.
 *
 * Every pair records its CURRENT result per theme. The M10.0 baseline has known failures, listed
 * here as 'fail' with the milestone that fixes them (M10.1, new tokens). The test fails when a
 * result differs from what is recorded, in either direction: a regression fails, and so does a
 * fixed pair that is still marked 'fail', so the list must be updated as issues are fixed.
 * A calculation is not a browser test: Playwright and axe check rendered pages separately.
 */
import { describe, expect, it } from 'vitest'
import tokensCss from './tokens.css?raw'

type Theme = 'light' | 'dark'
type Outcome = 'pass' | 'fail'

function declarations(block: string): Map<string, string> {
  const vars = new Map<string, string>()
  for (const match of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) vars.set(match[1], match[2].trim())
  return vars
}

function blockAfter(selector: string, from = 0): string {
  const start = tokensCss.indexOf(selector, from)
  if (start < 0) throw new Error(`${selector} not found in tokens.css`)
  const open = tokensCss.indexOf('{', start)
  const close = tokensCss.indexOf('}', open)
  return tokensCss.slice(open + 1, close)
}

const LIGHT = declarations(blockAfter(':root {'))
const DARK_ATTRIBUTE = declarations(blockAfter(":root[data-theme='dark']"))
const DARK_MEDIA = declarations(
  blockAfter(":root:not([data-theme='light'])", tokensCss.indexOf('prefers-color-scheme: dark')),
)

function themeVars(theme: Theme): Map<string, string> {
  return theme === 'light' ? LIGHT : new Map([...LIGHT, ...DARK_ATTRIBUTE])
}

function resolve(name: string, theme: Theme, seen: string[] = []): string {
  const vars = themeVars(theme)
  const value = vars.get(name)
  if (value === undefined) throw new Error(`${name} is not defined for the ${theme} theme`)
  const reference = /^var\((--[\w-]+)\)$/.exec(value)
  if (!reference) return value
  if (seen.includes(name)) throw new Error(`circular reference at ${name}`)
  return resolve(reference[1], theme, [...seen, name])
}

function luminance(hex: string): number {
  const digits = hex.replace('#', '')
  const full = digits.length === 3 ? [...digits].map((d) => d + d).join('') : digits
  const channels = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (high + 0.05) / (low + 0.05)
}

interface Pair {
  use: string
  foreground: string
  background: string
  /** 4.5 for normal text, 3 for UI component boundaries and focus indicators (WCAG 1.4.3 / 1.4.11). */
  minimum: number
  expected: Record<Theme, Outcome>
}

const PASS: Record<Theme, Outcome> = { light: 'pass', dark: 'pass' }
// Known M10.0 baseline failures; all are fixed by the new tokens planned for M10.1.
const DARK_FAILS: Record<Theme, Outcome> = { light: 'pass', dark: 'fail' }
const LIGHT_FAILS: Record<Theme, Outcome> = { light: 'fail', dark: 'pass' }
const BOTH_FAIL: Record<Theme, Outcome> = { light: 'fail', dark: 'fail' }

const PAIRS: Pair[] = [
  { use: 'body text on the page', foreground: '--text-primary', background: '--surface-page', minimum: 4.5, expected: PASS },
  { use: 'body text on cards', foreground: '--text-primary', background: '--surface-card', minimum: 4.5, expected: PASS },
  { use: 'secondary text (buttons, navigation, subtitles)', foreground: '--text-secondary', background: '--surface-card', minimum: 4.5, expected: PASS },
  { use: 'secondary text on sunken surfaces (Uploaded pill)', foreground: '--text-secondary', background: '--surface-sunken', minimum: 4.5, expected: PASS },
  { use: 'muted text on cards (meta, hints)', foreground: '--text-muted', background: '--surface-card', minimum: 4.5, expected: LIGHT_FAILS },
  { use: 'muted text on the page', foreground: '--text-muted', background: '--surface-page', minimum: 4.5, expected: LIGHT_FAILS },
  { use: 'muted text on sunken surfaces (Unknown badge)', foreground: '--text-muted', background: '--surface-sunken', minimum: 4.5, expected: BOTH_FAIL },
  { use: 'links on the page', foreground: '--accent-600', background: '--surface-page', minimum: 4.5, expected: DARK_FAILS },
  { use: 'links on cards', foreground: '--accent-600', background: '--surface-card', minimum: 4.5, expected: DARK_FAILS },
  { use: 'active navigation item', foreground: '--accent-700', background: '--accent-50', minimum: 4.5, expected: DARK_FAILS },
  { use: 'Processing pill', foreground: '--accent-600', background: '--accent-50', minimum: 4.5, expected: DARK_FAILS },
  { use: 'user message bubble, logo, send button', foreground: '--text-on-accent', background: '--accent-500', minimum: 4.5, expected: PASS },
  { use: 'primary button (sign-in screen)', foreground: '--text-on-accent', background: '--accent-600', minimum: 4.5, expected: PASS },
  { use: 'Healthy / Processed badge', foreground: '--success-500', background: '--success-50', minimum: 4.5, expected: BOTH_FAIL },
  { use: 'Degraded badge', foreground: '--warning-500', background: '--warning-50', minimum: 4.5, expected: BOTH_FAIL },
  { use: 'warning notes on cards', foreground: '--warning-500', background: '--surface-card', minimum: 4.5, expected: BOTH_FAIL },
  { use: 'Unavailable / Failed badge', foreground: '--danger-500', background: '--danger-50', minimum: 4.5, expected: DARK_FAILS },
  { use: 'error text on the page', foreground: '--danger-500', background: '--surface-page', minimum: 4.5, expected: DARK_FAILS },
  { use: 'error text on cards', foreground: '--danger-500', background: '--surface-card', minimum: 4.5, expected: DARK_FAILS },
  { use: 'field borders (composer, text areas)', foreground: '--border-default', background: '--surface-card', minimum: 3, expected: BOTH_FAIL },
  { use: 'focus ring on cards', foreground: '--accent-500', background: '--surface-card', minimum: 3, expected: DARK_FAILS },
  { use: 'focus ring on the page', foreground: '--accent-500', background: '--surface-page', minimum: 3, expected: PASS },
]

describe('design tokens', () => {
  it('define the same dark theme for the OS preference and for data-theme="dark"', () => {
    expect(Object.fromEntries(DARK_MEDIA)).toEqual(Object.fromEntries(DARK_ATTRIBUTE))
  })

  it('compute ratios with the WCAG formula', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5)
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 2)
  })
})

describe.each(['light', 'dark'] as const)('contrast in the %s theme', (theme) => {
  it.each(PAIRS)('$use ($foreground on $background)', ({ foreground, background, minimum, expected }) => {
    const ratio = contrastRatio(resolve(foreground, theme), resolve(background, theme))
    const outcome: Outcome = ratio >= minimum ? 'pass' : 'fail'
    expect(
      outcome,
      `${theme}: ${foreground} on ${background} is ${ratio.toFixed(2)}:1 (needs ${minimum}:1); ` +
        `recorded as '${expected[theme]}' — update the list if this changed on purpose`,
    ).toBe(expected[theme])
  })
})
