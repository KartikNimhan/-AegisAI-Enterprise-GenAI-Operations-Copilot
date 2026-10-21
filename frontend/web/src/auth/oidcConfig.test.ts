import { WebStorageStateStore } from 'oidc-client-ts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OIDC_SCOPE, buildOidcSettings, getOidcConfig } from './oidcConfig'

afterEach(() => {
  delete window.__AEGIS_CONFIG__
  vi.unstubAllEnvs()
})

describe('getOidcConfig', () => {
  it('reads the runtime block written at container start', () => {
    window.__AEGIS_CONFIG__ = { oidc: { authority: 'https://idp.example.test/realms/aegis', clientId: 'aegis-web' } }

    expect(getOidcConfig()).toEqual({
      authority: 'https://idp.example.test/realms/aegis',
      clientId: 'aegis-web',
    })
  })

  it('falls back to the build-time variables for local development', () => {
    vi.stubEnv('VITE_OIDC_AUTHORITY', 'http://localhost:18081/realms/aegis')
    vi.stubEnv('VITE_OIDC_CLIENT_ID', 'aegis-web')

    expect(getOidcConfig()).toEqual({ authority: 'http://localhost:18081/realms/aegis', clientId: 'aegis-web' })
  })

  it('is null unless both values are present (an empty runtime value counts as absent)', () => {
    expect(getOidcConfig()).toBeNull()

    window.__AEGIS_CONFIG__ = { oidc: { authority: 'https://idp.example.test/realms/aegis', clientId: '' } }
    expect(getOidcConfig()).toBeNull()

    window.__AEGIS_CONFIG__ = { oidc: { authority: '', clientId: 'aegis-web' } }
    expect(getOidcConfig()).toBeNull()
  })
})

describe('buildOidcSettings', () => {
  const settings = buildOidcSettings({ authority: 'https://idp.example.test/realms/aegis', clientId: 'aegis-web' })

  it('uses the authorization-code flow with no client secret (a public client with PKCE)', () => {
    expect(settings.response_type).toBe('code')
    expect(settings.client_id).toBe('aegis-web')
    expect(settings.authority).toBe('https://idp.example.test/realms/aegis')
    expect(settings).not.toHaveProperty('client_secret')
  })

  it('returns to this origin after signing in and out', () => {
    expect(settings.redirect_uri).toBe(`${window.location.origin}/`)
    expect(settings.post_logout_redirect_uri).toBe(`${window.location.origin}/`)
  })

  it('asks only for identity scopes and keeps tokens in sessionStorage', () => {
    expect(settings.scope).toBe(OIDC_SCOPE)
    expect(settings.scope?.split(' ')).toEqual(['openid', 'profile', 'email'])
    expect(settings.userStore).toBeInstanceOf(WebStorageStateStore)
    expect(settings.automaticSilentRenew).toBe(true)
  })
})
