/**
 * The PRODUCTION build under the PRODUCTION Content-Security-Policy (M10.0).
 *
 * `vite preview` serves `dist/`; every same-origin response gets the policy that
 * docker-entrypoint.sh would send for this configuration (support/policy.ts reads the template
 * from that script), and `config.js` is replaced by what the script would write. The API and the
 * identity provider are mocked in the browser (support/backend.ts). The policy is NOT weakened:
 * the test only observes violations, and a control test proves the policy is being enforced.
 *
 * Not covered here (see CLAUDE.md, M10.0): nginx itself (headers, caching, the /api proxy) and a
 * real sign-in redirect; the container image is built in CI but not run.
 */
import { expect, test, type Page } from '@playwright/test'
import { mockBackend, mockIdentityProvider, storedSession } from './support/backend.ts'
import { policyTemplate, productionPolicy } from './support/policy.ts'

const APP_ORIGIN = 'http://127.0.0.1:4173'
// Same-origin API, as when nginx proxies /api/ to the backend. The identity provider is on its
// own origin, as in production; `.test` names never resolve, and page.route answers them.
const API_BASE_URL = APP_ORIGIN
const OIDC_AUTHORITY = 'https://idp.aegis.test/realms/aegis'
const OIDC_CLIENT_ID = 'aegisai-web'
const POLICY = productionPolicy({ apiBaseUrl: API_BASE_URL, oidcAuthority: OIDC_AUTHORITY })

/** What docker-entrypoint.sh writes into config.js for this configuration. */
const CONFIG_JS =
  `window.__AEGIS_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}", ` +
  `oidc: { authority: "${OIDC_AUTHORITY}", clientId: "${OIDC_CLIENT_ID}" } };\n`

declare global {
  interface Window {
    __cspViolations: string[]
  }
}

async function servePolicy(page: Page): Promise<void> {
  // Registered first, so the more specific routes below take precedence (Playwright checks the
  // most recently added route first).
  await page.route(`${APP_ORIGIN}/**`, async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': POLICY } })
  })
  await page.route(`${APP_ORIGIN}/config.js`, (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      headers: { 'content-security-policy': POLICY, 'cache-control': 'no-store' },
      body: CONFIG_JS,
    }),
  )
}

async function recordViolations(page: Page): Promise<string[]> {
  const console: string[] = []
  page.on('console', (message) => {
    if (/content security policy/i.test(message.text())) console.push(message.text())
  })
  await page.addInitScript(() => {
    window.__cspViolations = []
    document.addEventListener('securitypolicyviolation', (event) => {
      window.__cspViolations.push(`${event.violatedDirective} blocked ${event.blockedURI || '(inline)'}`)
    })
  })
  return console
}

async function violations(page: Page): Promise<string[]> {
  return page.evaluate(() => window.__cspViolations)
}

test.describe('production build under the production CSP', () => {
  test('the policy template is as strict as recorded (no unsafe-inline, unsafe-eval or wildcards)', () => {
    const template = policyTemplate()
    for (const directive of ["default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src 'self'", "font-src 'self'", "object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'"]) {
      expect(template).toContain(directive)
    }
    expect(template).not.toMatch(/unsafe-inline|unsafe-eval|\*/)
    expect(POLICY).toContain(`connect-src 'self' ${APP_ORIGIN} https://idp.aegis.test`)
  })

  test('the document is served with the policy, and the policy is enforced (control)', async ({ page }) => {
    await servePolicy(page)
    await recordViolations(page)
    await mockIdentityProvider(page, OIDC_AUTHORITY, APP_ORIGIN)
    const response = await page.goto('/')
    expect(response?.headers()['content-security-policy']).toBe(POLICY)

    // An inline script must be refused: proof the browser is applying the policy.
    await page.evaluate(() => {
      const script = document.createElement('script')
      script.textContent = 'window.__inlineRan = true'
      document.body.append(script)
    })
    await expect.poll(() => violations(page)).toContainEqual(expect.stringContaining('script-src'))
    expect(await page.evaluate(() => (window as unknown as { __inlineRan?: boolean }).__inlineRan)).toBeUndefined()
  })

  test('the signed-out screen renders with no policy violations', async ({ page }) => {
    await servePolicy(page)
    const console = await recordViolations(page)
    await mockIdentityProvider(page, OIDC_AUTHORITY, APP_ORIGIN)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible()
    expect(await violations(page)).toEqual([])
    expect(console).toEqual([])
  })

  test('every page of the signed-in app renders with no policy violations', async ({ page }) => {
    await servePolicy(page)
    const console = await recordViolations(page)
    await mockIdentityProvider(page, OIDC_AUTHORITY, APP_ORIGIN)
    const unexpected = await mockBackend(page, APP_ORIGIN)
    const session = storedSession(OIDC_AUTHORITY, OIDC_CLIENT_ID)
    await page.addInitScript(({ key, value }) => window.sessionStorage.setItem(key, value), session)

    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Copilot')
    const nav = page.getByRole('navigation')
    for (const [title, ready] of [
      ['Conversations', 'CSP test conversation'],
      ['Documents', 'csp-test.pdf'],
      ['Memory', 'Nothing remembered yet'],
      ['Operations', 'Total documents'],
      ['System Status', 'Database (PostgreSQL)'],
    ] as const) {
      await nav.getByRole('link', { name: title }).click()
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(title)
      await expect(page.getByText(ready).first()).toBeVisible()
    }

    expect(await violations(page)).toEqual([])
    expect(console).toEqual([])
    expect(unexpected).toEqual([])
  })
})
