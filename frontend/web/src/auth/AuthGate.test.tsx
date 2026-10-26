import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installFetchMock } from '../test/mockFetch'
import { useAccount } from './AccountContext'
import { AuthGate } from './AuthGate'
import { AuthStateContext, type AuthState, type AuthUser } from './AuthContext'
import { setUnauthorizedHandler } from './token'

const USER: AuthUser = {
  subject: 'sub-123',
  issuer: 'https://idp.example.test/realms/aegis',
  email: 'ada@example.test',
}

function state(overrides: Partial<AuthState> = {}): AuthState {
  return {
    status: 'signed_in',
    user: USER,
    message: null,
    signIn: vi.fn(),
    signOut: vi.fn(),
    ...overrides,
  }
}

function renderGate(auth: AuthState) {
  return render(
    <AuthStateContext.Provider value={auth}>
      <AuthGate>
        <p>the application</p>
      </AuthGate>
    </AuthStateContext.Provider>,
  )
}

const ME = { user_id: 'u1', organization_id: 'o1', email: 'ada@example.test', role: 'member' }

/** Stands in for the app: shows the account the gate provides. */
function ShowAccount() {
  const account = useAccount()
  return <p>{account ? `${account.email} is ${account.role}` : 'no account'}</p>
}

afterEach(() => {
  setUnauthorizedHandler(null)
})

describe('AuthGate before sign-in', () => {
  it('shows progress while the session is being checked, never the app', () => {
    renderGate(state({ status: 'loading', user: null }))

    expect(screen.getByRole('status')).toHaveTextContent(/checking your session/i)
    expect(screen.queryByText('the application')).not.toBeInTheDocument()
  })

  it('explains that sign-in is not configured instead of showing a dead button', () => {
    renderGate(state({ status: 'unconfigured', user: null }))

    expect(screen.getByRole('alert')).toHaveTextContent(/no identity provider settings/i)
    expect(screen.getByText('OIDC_AUTHORITY')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText('the application')).not.toBeInTheDocument()
  })

  it('offers a Sign in button that starts sign-in', async () => {
    const auth = state({ status: 'signed_out', user: null })
    renderGate(auth)

    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(auth.signIn).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('the application')).not.toBeInTheDocument()
  })

  it('says why the user is signed out, such as an expired session', () => {
    renderGate(state({ status: 'signed_out', user: null, message: 'Your session has expired. Please sign in again.' }))

    expect(screen.getByRole('alert')).toHaveTextContent(/session has expired/i)
  })

  it('shows a sign-in failure with a way to retry', async () => {
    const auth = state({ status: 'error', user: null, message: 'Sign-in failed: network down' })
    renderGate(auth)

    expect(screen.getByRole('alert')).toHaveTextContent('Sign-in failed: network down')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(auth.signIn).toHaveBeenCalledTimes(1)
  })
})

describe('AuthGate after sign-in', () => {
  it('shows the app only once the backend recognizes the account', async () => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: ME }))
    renderGate(state())

    expect(screen.queryByText('the application')).not.toBeInTheDocument()
    expect(await screen.findByText('the application')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/v1/auth/me'))).toBe(true)
  })

  it('tells an unlinked person what to give an administrator, and never shows the app', async () => {
    installFetchMock(() => ({
      status: 403,
      body: { error: { code: 'forbidden', message: 'Access denied' } },
    }))
    const auth = state()
    renderGate(auth)

    expect(await screen.findByText('Your account is not set up yet')).toBeInTheDocument()
    expect(screen.getByText('sub-123')).toBeInTheDocument()
    expect(screen.getByText('https://idp.example.test/realms/aegis')).toBeInTheDocument()
    expect(screen.getByText('ada@example.test')).toBeInTheDocument()
    expect(screen.queryByText('the application')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(auth.signOut).toHaveBeenCalledTimes(1)
  })

  it('reports an outage as such (not as a missing account) and retries on request', async () => {
    let healthy = false
    const fetchMock = installFetchMock(() =>
      healthy
        ? { status: 200, body: ME }
        : { status: 503, body: { error: { code: 'auth_unavailable', message: 'down' } } },
    )
    renderGate(state())

    expect(await screen.findByRole('alert')).toHaveTextContent(/temporarily unavailable/i)
    expect(screen.queryByText('Your account is not set up yet')).not.toBeInTheDocument()

    healthy = true
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('the application')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/auth/me'))).toHaveLength(2)
  })

  it('leaves a rejected token to the auth layer: the app is not shown', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    installFetchMock(() => ({
      status: 401,
      body: { error: { code: 'unauthorized', message: 'Authentication required' } },
    }))
    renderGate(state())

    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('the application')).not.toBeInTheDocument()
    expect(screen.queryByText('Your account is not set up yet')).not.toBeInTheDocument()
  })

  it('checks again when a different person signs in', async () => {
    const fetchMock = installFetchMock(() => ({ status: 200, body: ME }))
    const { rerender } = renderGate(state())
    await screen.findByText('the application')

    rerender(
      <AuthStateContext.Provider value={state({ user: { ...USER, subject: 'sub-other' } })}>
        <AuthGate>
          <p>the application</p>
        </AuthGate>
      </AuthStateContext.Provider>,
    )

    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/auth/me'))).toHaveLength(2),
    )
  })

  it.each(['admin', 'member'])('hands the app the confirmed account, role %s included', async (role) => {
    installFetchMock(() => ({ status: 200, body: { ...ME, role } }))
    render(
      <AuthStateContext.Provider value={state()}>
        <AuthGate>
          <ShowAccount />
        </AuthGate>
      </AuthStateContext.Provider>,
    )

    expect(await screen.findByText(`ada@example.test is ${role}`)).toBeInTheDocument()
  })
})
