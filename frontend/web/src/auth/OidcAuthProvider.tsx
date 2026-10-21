import { useCallback, useLayoutEffect, useMemo, useState, type ReactNode } from 'react'
import { AuthProvider as OidcProvider, useAuth } from 'react-oidc-context'
import { AuthStateContext, type AuthState, type AuthUser } from './AuthContext'
import { buildOidcSettings, getOidcConfig } from './oidcConfig'
import { setAccessToken, setUnauthorizedHandler } from './token'

const UNCONFIGURED: AuthState = {
  status: 'unconfigured',
  user: null,
  message: null,
  signIn: () => undefined,
  signOut: () => undefined,
}

/** After the provider redirects back with `?code=&state=`, drop them from the URL. */
function clearCallbackParams(): void {
  window.history.replaceState({}, document.title, window.location.pathname)
}

/**
 * Sign-in for the whole app. Without identity-provider settings there is nothing
 * to sign in to, and the gate says so; with them, `react-oidc-context` runs the
 * authorization-code + PKCE flow and this component translates its state into
 * the small `AuthState` the rest of the app uses.
 */
export function OidcAuthProvider({ children }: { children: ReactNode }) {
  const settings = useMemo(() => {
    const config = getOidcConfig()
    return config ? buildOidcSettings(config) : null
  }, [])

  if (!settings) {
    return <AuthStateContext.Provider value={UNCONFIGURED}>{children}</AuthStateContext.Provider>
  }
  return (
    <OidcProvider {...settings} onSigninCallback={clearCallbackParams}>
      <Bridge>{children}</Bridge>
    </OidcProvider>
  )
}

function toAuthUser(profile: { sub: string; iss?: string; email?: string; name?: string; preferred_username?: unknown }): AuthUser {
  return {
    subject: profile.sub,
    issuer: profile.iss ?? '',
    email: profile.email,
    name: profile.name ?? (typeof profile.preferred_username === 'string' ? profile.preferred_username : undefined),
  }
}

function Bridge({ children }: { children: ReactNode }) {
  const auth = useAuth()
  // The token the backend refused. The user is treated as signed out until a
  // different token arrives; nothing redirects automatically, so a provider or
  // audience misconfiguration shows a message instead of looping.
  const [rejectedToken, setRejectedToken] = useState<string | null>(null)
  const [signInError, setSignInError] = useState<string | null>(null)

  const accessToken = auth.user?.access_token ?? null
  const rejected = accessToken !== null && accessToken === rejectedToken
  const activeToken = rejected ? null : accessToken

  // Layout effects run before any child's effect, so the first API call a signed-in
  // child makes already carries the token.
  useLayoutEffect(() => {
    setAccessToken(activeToken)
  }, [activeToken])

  const removeUser = auth.removeUser
  useLayoutEffect(() => {
    setUnauthorizedHandler(() => {
      setRejectedToken(accessToken)
      void removeUser()
    })
    return () => setUnauthorizedHandler(null)
  }, [accessToken, removeUser])

  const signinRedirect = auth.signinRedirect
  const signoutRedirect = auth.signoutRedirect
  const signIn = useCallback(() => {
    setSignInError(null)
    signinRedirect().catch((error: unknown) => {
      setSignInError(error instanceof Error ? error.message : 'Could not start sign-in.')
    })
  }, [signinRedirect])
  const signOut = useCallback(() => {
    setAccessToken(null)
    signoutRedirect().catch(() => void removeUser())
  }, [signoutRedirect, removeUser])

  const profile = auth.user?.profile
  const authError = auth.error?.message ?? null
  const state = useMemo<AuthState>(() => {
    const user = activeToken && profile ? toAuthUser(profile) : null
    if (user) return { status: 'signed_in', user, message: null, signIn, signOut }
    if (auth.isLoading) return { status: 'loading', user: null, message: null, signIn, signOut }
    const failure = signInError ?? authError
    if (failure) {
      return { status: 'error', user: null, message: `Sign-in failed: ${failure}`, signIn, signOut }
    }
    const message = rejected ? 'Your session has expired. Please sign in again.' : null
    return { status: 'signed_out', user: null, message, signIn, signOut }
  }, [activeToken, profile, auth.isLoading, signInError, authError, rejected, signIn, signOut])

  return <AuthStateContext.Provider value={state}>{children}</AuthStateContext.Provider>
}
