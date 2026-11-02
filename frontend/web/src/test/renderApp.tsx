import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import type { Me } from '../api/auth'
import { AccountContext } from '../auth/AccountContext'

export const MEMBER_ACCOUNT: Me = {
  user_id: 'user-member',
  organization_id: 'org-test',
  email: 'member@example.test',
  role: 'member',
}

export const ADMIN_ACCOUNT: Me = {
  ...MEMBER_ACCOUNT,
  user_id: 'user-admin',
  email: 'admin@example.test',
  role: 'admin',
}

/** Renders the app as the auth gate does once an account is confirmed (a member unless given). */
export function renderApp(initialPath = '/', account: Me | null = MEMBER_ACCOUNT) {
  return render(
    <AccountContext.Provider value={account}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </AccountContext.Provider>,
  )
}
