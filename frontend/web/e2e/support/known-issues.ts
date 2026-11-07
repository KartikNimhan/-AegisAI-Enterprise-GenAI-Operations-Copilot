/**
 * Accessibility issues KNOWN at the M10.0 baseline (measured 2026-11-02 in Chromium with axe-core
 * 4.14.0, preview mode, 1280 px). Keys are `<route> <theme>`; values are the violated axe rule and
 * the exact number of affected elements (the preview's mock data is fixed, so counts are stable).
 *
 * The test fails if a page has any other violation, MORE affected elements, or FEWER (an
 * improvement must be recorded here, so the list only ever shrinks).
 *
 * - color-contrast (serious): text below 4.5:1, on every page in both themes. FIXED in M10.1
 *   (2026-11-03): the new tokens pass every pair (src/styles/tokens.contrast.test.ts) and axe finds
 *   no contrast violation on any page.
 * - empty-table-header (minor): the Documents table's actions column header had an aria-label but
 *   no text. FIXED in M10.8 (2026-11-04): it has visually hidden text.
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
  // M10.2 (2026-11-04): the sidebar is a drawer below 768 px and the Copilot header wraps, so
  // nothing overflows at 375 px any more. Re-measured in Chromium; the M10.0 values were
  // 375 px: Copilot 422/135, Documents 149/135, Memory 206/135, Operations 205/135, System 216/135.
  375: {},
  // M10.8 (2026-11-04): the Documents table stacks when its own width is below 640 px, so it no
  // longer overflows at 768 px (M10.0 measurement 605/528).
  768: {},
  1280: {},
}

export const KNOWN_ISSUES: Record<string, Record<string, number>> = {
  // M10.1 (2026-11-03): every color-contrast violation is gone in both themes. M10.8 (2026-11-04):
  // the Documents empty-table-header is fixed too; no known axe violation remains on any page.
}
