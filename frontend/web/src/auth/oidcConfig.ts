/**
 * Identity-provider settings for the browser sign-in (OIDC authorization-code
 * flow with PKCE, a public client: there is no client secret anywhere in the
 * frontend). Resolution order mirrors `src/config.ts`: the runtime
 * `window.__AEGIS_CONFIG__.oidc` block written at container start, then
 * `VITE_OIDC_AUTHORITY` / `VITE_OIDC_CLIENT_ID` for `npm run dev`.
 */

import { WebStorageStateStore, type UserManagerSettings } from 'oidc-client-ts'

export interface OidcConfig {
  /** The provider's issuer URL (the realm URL for Keycloak). */
  authority: string
  /** The public client's id in the provider. */
  clientId: string
}

export function getOidcConfig(): OidcConfig | null {
  const runtime = window.__AEGIS_CONFIG__?.oidc
  const authority = runtime?.authority || (import.meta.env.VITE_OIDC_AUTHORITY as string | undefined)
  const clientId = runtime?.clientId || (import.meta.env.VITE_OIDC_CLIENT_ID as string | undefined)
  if (!authority || !clientId) return null
  return { authority, clientId }
}

export const OIDC_SCOPE = 'openid profile email'

export function buildOidcSettings(config: OidcConfig): UserManagerSettings {
  const origin = window.location.origin
  return {
    authority: config.authority,
    client_id: config.clientId,
    redirect_uri: `${origin}/`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: 'code', // authorization code + PKCE; never the implicit flow
    scope: OIDC_SCOPE,
    // Tokens live for the browser tab only (sessionStorage), not across restarts.
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    // Renewal uses the refresh token when the provider issued one.
    automaticSilentRenew: true,
    loadUserInfo: false,
  }
}
