import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthState } from './AuthContext'
import { OidcAuthProvider } from './OidcAuthProvider'
import { getAccessToken, notifyUnauthorized, setAccessToken, setUnauthorizedHandler } from './token'

interface FakeUser {
  access_token: string
  profile: { sub: string; iss?: string; email?: string; name?: string }
}
interface FakeAuth {
  isLoading: boolean
  user: FakeUser | null | undefined
  error: Error | undefined
  signinRedirect: ReturnType<typeof vi.fn>
  signoutRedirect: ReturnType<typeof vi.fn>
  removeUser: ReturnType<typeof vi.fn>
}

// Stands in for react-oidc-context so the translation into AuthState is what is tested.
const mocks = vi.hoisted(() => ({ auth: {} as FakeAuth }))
vi.mock('react-oidc-context', async () => {
  const React = await import('react')
  return {
    AuthProvider: (props: { children: React.ReactNode }) =>
      React.createElement(React.Fragment, null, props.children),
    useAuth: () => mocks.auth,
  }
})

function signedInUser(token = 'tok-1'): FakeUser {
  return {
    access_token: token,
    profile: { sub: 'sub-1', iss: 'https://idp.example.test/realms/aegis', email: 'ada@example.test' },
  }
}

function Probe() {
  const auth = useAuthState()
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="message">{auth.message ?? ''}</p>
      <p data-testid="email">{auth.user?.email ?? ''}</p>
      <button type="button" onClick={auth.signIn}>
        sign-in
      </button>
      <button type="button" onClick={auth.signOut}>
        sign-out
      </button>
    </div>
  )
}

function renderProvider() {
  return render(
    <OidcAuthProvider>
      <Probe />
    </OidcAuthProvider>,
  )
}

const status = () => screen.getByTestId('status').textContent

beforeEach(() => {
  window.__AEGIS_CONFIG__ = { oidc: { authority: 'https://idp.example.test/realms/aegis', clientId: 'aegis-web' } }
  mocks.auth = {
    isLoading: false,
    user: null,
    error: undefined,
    signinRedirect: vi.fn(async () => undefined),
    signoutRedirect: vi.fn(async () => undefined),
    removeUser: vi.fn(async () => undefined),
  }
})

afterEach(() => {
  delete window.__AEGIS_CONFIG__
  setAccessToken(null)
  setUnauthorizedHandler(null)
  vi.unstubAllEnvs()
})

describe('OidcAuthProvider', () => {
  it('reports "unconfigured" when there are no identity provider settings', () => {
    delete window.__AEGIS_CONFIG__
    renderProvider()

    expect(status()).toBe('unconfigured')
  })

  it('is loading while the session is restored, then signed out without a user', () => {
    mocks.auth.isLoading = true
    const { unmount } = renderProvider()
    expect(status()).toBe('loading')
    unmount()

    mocks.auth.isLoading = false
    renderProvider()
    expect(status()).toBe('signed_out')
  })

  it('is signed in with a user, and gives the API client the access token', () => {
    mocks.auth.user = signedInUser('tok-1')
    renderProvider()

    expect(status()).toBe('signed_in')
    expect(screen.getByTestId('email')).toHaveTextContent('ada@example.test')
    expect(getAccessToken()).toBe('tok-1')
  })

  it('shows a failure from the provider as an error with the reason', () => {
    mocks.auth.error = new Error('No matching state found in storage')
    renderProvider()

    expect(status()).toBe('error')
    expect(screen.getByTestId('message')).toHaveTextContent('No matching state found in storage')
  })

  it('treats a token the backend rejected as signed out, clears it, and recovers with a new one', () => {
    mocks.auth.user = signedInUser('tok-1')
    const { rerender } = renderProvider()
    expect(status()).toBe('signed_in')

    act(() => notifyUnauthorized())

    expect(status()).toBe('signed_out')
    expect(screen.getByTestId('message')).toHaveTextContent(/session has expired/i)
    expect(getAccessToken()).toBeNull()
    expect(mocks.auth.removeUser).toHaveBeenCalledTimes(1)

    // Even if the stored user were still present, the refused token is not reused...
    rerender(
      <OidcAuthProvider>
        <Probe />
      </OidcAuthProvider>,
    )
    expect(status()).toBe('signed_out')

    // ...but a fresh sign-in (a different token) works at once, with no reload.
    mocks.auth.user = signedInUser('tok-2')
    rerender(
      <OidcAuthProvider>
        <Probe />
      </OidcAuthProvider>,
    )
    expect(status()).toBe('signed_in')
    expect(getAccessToken()).toBe('tok-2')
  })

  it('does not redirect on its own when a token is rejected (no redirect loops)', () => {
    mocks.auth.user = signedInUser('tok-1')
    renderProvider()

    act(() => notifyUnauthorized())

    expect(mocks.auth.signinRedirect).not.toHaveBeenCalled()
  })

  it('starts sign-in on request, and surfaces a failure to start it', async () => {
    renderProvider()
    await act(async () => screen.getByText('sign-in').click())
    expect(mocks.auth.signinRedirect).toHaveBeenCalledTimes(1)

    mocks.auth.signinRedirect = vi.fn(async () => {
      throw new Error('discovery failed')
    })
    const { unmount } = renderProvider()
    unmount()
    renderProvider()
    await act(async () => screen.getAllByText('sign-in')[1].click())

    expect(screen.getAllByTestId('status').map((el) => el.textContent)).toContain('error')
  })

  it('signs out through the provider, and just clears the session if that is unavailable', async () => {
    mocks.auth.user = signedInUser()
    renderProvider()
    await act(async () => screen.getByText('sign-out').click())
    expect(mocks.auth.signoutRedirect).toHaveBeenCalledTimes(1)
    expect(getAccessToken()).toBeNull()

    mocks.auth.signoutRedirect = vi.fn(async () => {
      throw new Error('no end_session_endpoint')
    })
    mocks.auth.user = signedInUser('tok-3')
    renderProvider()
    await act(async () => screen.getAllByText('sign-out')[1].click())

    expect(mocks.auth.removeUser).toHaveBeenCalled()
  })
})
