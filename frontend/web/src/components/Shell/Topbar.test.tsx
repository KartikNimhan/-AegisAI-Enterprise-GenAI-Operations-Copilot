import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AuthStateContext, type AuthState } from '../../auth/AuthContext'
import { installFetchMock } from '../../test/mockFetch'
import { Topbar } from './Topbar'

function signedIn(signOut = vi.fn()): AuthState {
  return {
    status: 'signed_in',
    user: { subject: 'sub-1', issuer: 'https://idp.example.test/realms/aegis', email: 'ada@example.test' },
    message: null,
    signIn: vi.fn(),
    signOut,
  }
}

describe('Topbar', () => {
  it('shows who is signed in and signs out on request', async () => {
    installFetchMock(() => ({ status: 200, body: {} }))
    const signOut = vi.fn()
    render(
      <AuthStateContext.Provider value={signedIn(signOut)}>
        <Topbar title="Documents" />
      </AuthStateContext.Provider>,
    )

    expect(screen.getByText('ada@example.test')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(signOut).toHaveBeenCalledTimes(1)
  })

  it('has no account controls without a sign-in provider', () => {
    installFetchMock(() => ({ status: 200, body: {} }))
    render(<Topbar title="Documents" />)

    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
  })
})
