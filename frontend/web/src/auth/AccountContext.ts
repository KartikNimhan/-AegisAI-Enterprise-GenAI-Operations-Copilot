import { createContext, useContext } from 'react'
import type { Me } from '../api/auth'

/**
 * The signed-in person's AegisAI account (`GET /api/v1/auth/me`), including their role. The auth
 * gate provides it once the backend has confirmed the account; without a provider it is `null`.
 */
export const AccountContext = createContext<Me | null>(null)

export function useAccount(): Me | null {
  return useContext(AccountContext)
}

/**
 * Whether to show administrator-only screens. Display only, and closed by default: an unknown
 * account is not an administrator. The backend enforces the same rule on its own (403).
 */
export function isAdmin(account: Me | null): boolean {
  return account?.role === 'admin'
}
