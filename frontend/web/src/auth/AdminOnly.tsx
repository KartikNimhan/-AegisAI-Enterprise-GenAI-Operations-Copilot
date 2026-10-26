import type { ReactNode } from 'react'
import { EmptyState } from '../components/EmptyState'
import { isAdmin, useAccount } from './AccountContext'

/**
 * Shows an administrator-only page to administrators. Everyone else gets a short notice instead of
 * a page whose request the backend would refuse (403); hiding it is not the protection itself.
 */
export function AdminOnly({ children }: { children: ReactNode }) {
  if (isAdmin(useAccount())) return <>{children}</>
  return (
    <EmptyState
      title="Administrators only"
      description="This page is available to administrators. Ask one if you need this information."
    />
  )
}
