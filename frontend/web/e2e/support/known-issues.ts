/**
 * Accessibility issues KNOWN at the M10.0 baseline (measured 2026-11-02 in Chromium with axe-core
 * 4.14.0, preview mode, 1280 px). Keys are `<route> <theme>`; values are the violated axe rule and
 * the exact number of affected elements (the preview's mock data is fixed, so counts are stable).
 *
 * The test fails if a page has any other violation, MORE affected elements, or FEWER (an
 * improvement must be recorded here, so the list only ever shrinks).
 *
 * - color-contrast (serious): text below 4.5:1, on every page in both themes. The causes are the
 *   current tokens (src/styles/tokens.contrast.test.ts lists each failing pair). Fix: M10.1.
 * - empty-table-header (minor): the Documents table's actions column header has an aria-label but
 *   no text. Fix: M10.8.
 */
/**
 * Horizontal overflow INSIDE the independently scrollable `<main>` element (its scrollWidth is
 * larger than its clientWidth), known at the M10.0 baseline. The whole document never overflows,
 * so a check of the document alone misses these (WCAG 1.4.10 reflow failures).
 *
 * MEASURED 2026-11-02 in Chromium 1248 on Windows (preview mode; the same in both themes), as
 * content width / visible width in CSS px. At 375 px the visible width is always 135 px: the fixed
 * 240 px sidebar takes the rest. The pixel values are a record, not the assertion: the test checks
 * the exact SET of overflowing pages per width, because content widths depend on font metrics,
 * which differ between operating systems.
 *
 * Fix: M10.2 (responsive shell: the sidebar becomes a drawer) and M10.8 (page layouts).
 */
export const KNOWN_MAIN_OVERFLOW: Record<number, Record<string, { content: number; visible: number }>> = {
  375: {
    '/': { content: 422, visible: 135 },
    '/documents': { content: 149, visible: 135 },
    '/memory': { content: 206, visible: 135 },
    '/operations': { content: 205, visible: 135 },
    '/system': { content: 216, visible: 135 },
  },
  768: {
    '/documents': { content: 605, visible: 528 },
  },
  1280: {},
}

export const KNOWN_ISSUES: Record<string, Record<string, number>> = {
  '/ light': { 'color-contrast': 2 },
  '/conversations light': { 'color-contrast': 3 },
  '/documents light': { 'color-contrast': 8, 'empty-table-header': 1 },
  '/memory light': { 'color-contrast': 4 },
  '/operations light': { 'color-contrast': 3 },
  '/system light': { 'color-contrast': 5 },
  '/ dark': { 'color-contrast': 2 },
  '/conversations dark': { 'color-contrast': 2 },
  '/documents dark': { 'color-contrast': 6, 'empty-table-header': 1 },
  '/memory dark': { 'color-contrast': 2 },
  '/operations dark': { 'color-contrast': 2 },
  '/system dark': { 'color-contrast': 5 },
}
