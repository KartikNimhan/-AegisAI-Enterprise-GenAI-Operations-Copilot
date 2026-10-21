import { createContext, useContext } from 'react'

export type AuthStatus = 'loading' | 'signed_out' | 'signed_in' | 'unconfigured' | 'error'

export interface AuthUser {
  /** The token's `sub` claim: what an operator links an internal account to. */
  subject: string
  /** The token's `iss` claim. */
  issuer: string
  email?: string
  name?: string
}

export interface AuthState {
  status: AuthStatus
  user: AuthUser | null
  /** Why the user is signed out or in error (an expired session, a failed sign-in). */
  message: string | null
  signIn: () => void
  signOut: () => void
}

export const AuthStateContext = createContext<AuthState | null>(null)

/** For the gate, which must have a provider above it. */
export function useAuthState(): AuthState {
  const state = useContext(AuthStateContext)
  if (!state) throw new Error('useAuthState must be used inside an auth provider')
  return state
}

/** For display-only components (the top bar) that also render without one. */
export function useOptionalAuthState(): AuthState | null {
  return useContext(AuthStateContext)
}
