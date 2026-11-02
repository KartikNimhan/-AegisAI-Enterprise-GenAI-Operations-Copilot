/**
 * A mock backend and identity provider for the production-CSP tests, served INSIDE the browser
 * with `page.route` (nothing listens on the network, nothing leaves the machine, no model calls).
 * The data is synthetic and deliberately small.
 */
import type { Page, Route } from '@playwright/test'

export const ADMIN = {
  user_id: 'user-admin',
  organization_id: 'org-test',
  email: 'admin@example.test',
  role: 'admin',
}

const WHEN = '2026-11-02T00:00:00Z'

const DOCUMENT = {
  id: '11111111-2222-3333-4444-555555555555',
  filename: 'csp-test.pdf',
  content_type: 'application/pdf',
  document_type: 'pdf',
  file_size: 2048,
  status: 'processed',
  error_message: null,
  page_count: 1,
  character_count: 120,
  metadata: null,
  created_at: WHEN,
  updated_at: WHEN,
  processed_at: WHEN,
}

/** GET responses by path. Anything else is answered 404 (and recorded as unexpected). */
const RESPONSES: Record<string, unknown> = {
  '/api/v1/auth/me': ADMIN,
  '/api/v1/documents': { items: [DOCUMENT], total: 1, limit: 100, offset: 0 },
  '/api/v1/conversations': [{ id: 'c1', title: 'CSP test conversation', created_at: WHEN, updated_at: WHEN }],
  '/api/v1/memories': [],
  '/api/v1/operations/summary': { total_documents: 1, documents_by_status: { processed: 1 } },
  '/api/v1/system/status': {
    database: 'ok',
    redis: 'ok',
    llm_configured: false,
    mcp_server: 'in-process',
    trusted_a2a_agents: [],
  },
}

/** Serves the mock API at `apiOrigin`. Returns the list of requests it did not expect. */
export async function mockBackend(page: Page, apiOrigin: string): Promise<string[]> {
  const unexpected: string[] = []
  await page.route(`${apiOrigin}/health`, (route) => route.fulfill({ json: { status: 'ok' } }))
  await page.route(`${apiOrigin}/api/**`, async (route: Route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && path in RESPONSES) {
      await route.fulfill({ json: RESPONSES[path] })
      return
    }
    unexpected.push(`${request.method()} ${path}`)
    await route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Not in the CSP test' } } })
  })
  return unexpected
}

/** OIDC discovery for the mock identity provider (only fetched if the client needs it). */
export async function mockIdentityProvider(page: Page, authority: string, appOrigin: string): Promise<void> {
  await page.route(`${authority}/**`, (route) =>
    route.fulfill({
      headers: { 'access-control-allow-origin': appOrigin },
      json: {
        issuer: authority,
        authorization_endpoint: `${authority}/protocol/openid-connect/auth`,
        token_endpoint: `${authority}/protocol/openid-connect/token`,
        end_session_endpoint: `${authority}/protocol/openid-connect/logout`,
        jwks_uri: `${authority}/protocol/openid-connect/certs`,
        response_types_supported: ['code'],
        subject_types_supported: ['public'],
        id_token_signing_alg_values_supported: ['RS256'],
      },
    }),
  )
}

/**
 * A signed-in session as oidc-client-ts stores it (sessionStorage, `oidc.user:<authority>:<client>`).
 * The token is a placeholder: the mock backend never checks it, and no real provider is involved.
 */
export function storedSession(authority: string, clientId: string): { key: string; value: string } {
  return {
    key: `oidc.user:${authority}:${clientId}`,
    value: JSON.stringify({
      access_token: 'csp-test-placeholder-token',
      token_type: 'Bearer',
      scope: 'openid profile email',
      profile: { sub: 'csp-test-subject', iss: authority, email: ADMIN.email },
      expires_at: Math.floor(Date.now() / 1000) + 3600,
    }),
  }
}
