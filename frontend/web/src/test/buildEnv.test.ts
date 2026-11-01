import { describe, expect, it, vi } from 'vitest'
import { getOidcConfig } from '../auth/oidcConfig'
import { getApiBaseUrl } from '../config'

// Regression test for src/test/setup.ts: build-time settings from a developer's `.env.local` must
// not reach tests. Each check compares against the empty string, so a failure never prints a value.
const NAMES = ['VITE_OIDC_AUTHORITY', 'VITE_OIDC_CLIENT_ID', 'VITE_API_BASE_URL'] as const

describe('build-time settings inside tests', () => {
  it('are empty, whatever a local .env.local contains', () => {
    const empty = NAMES.map((name) => import.meta.env[name] === '')

    expect(empty).toEqual([true, true, true])
  })

  it('leave the application unconfigured, as in CI', () => {
    expect(getOidcConfig()).toBeNull()
    expect(getApiBaseUrl()).toBe('http://localhost:8000')
  })

  it('still let a test stub a value on purpose', () => {
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'http://localhost:18081/realms/aegis')
    vi.stubEnv('VITE_OIDC_CLIENT_ID', 'aegis-web')

    expect(getOidcConfig()).toEqual({ authority: 'http://localhost:18081/realms/aegis', clientId: 'aegis-web' })
  })

  it('are empty again in the next test (the stubs above were undone)', () => {
    const empty = NAMES.map((name) => import.meta.env[name] === '')

    expect(empty).toEqual([true, true, true])
    expect(getOidcConfig()).toBeNull()
  })
})
