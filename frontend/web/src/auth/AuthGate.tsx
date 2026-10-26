import { useEffect, useState, type ReactNode } from 'react'
import { getMe, type Me } from '../api/auth'
import { BackendError } from '../api/client'
import { friendlyMessage } from '../utils/errors'
import { AccountContext } from './AccountContext'
import { useAuthState, type AuthState } from './AuthContext'
import styles from './AuthGate.module.css'

function Screen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.screen}>
      <section className={styles.panel} aria-labelledby="auth-title">
        <h1 id="auth-title" className={styles.title}>
          {title}
        </h1>
        {children}
      </section>
    </div>
  )
}

type Check =
  | { kind: 'ok'; account: Me }
  | { kind: 'not_provisioned' }
  | { kind: 'failed'; message: string }

/**
 * Everything between "the page loaded" and "the app is usable": signing in, and
 * confirming that the backend knows the signed-in person. The app below it never
 * renders for someone who is not both, and it receives the confirmed account.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useAuthState()

  switch (auth.status) {
    case 'loading':
      return (
        <Screen title="Signing in…">
          <p role="status" className={styles.text}>
            Checking your session.
          </p>
        </Screen>
      )
    case 'unconfigured':
      return (
        <Screen title="Sign-in is not configured">
          <p role="alert" className={styles.alert}>
            This deployment has no identity provider settings, so nobody can sign in.
          </p>
          <p className={styles.text}>
            Set <code>OIDC_AUTHORITY</code> and <code>OIDC_CLIENT_ID</code> for the frontend (see
            the README, “Authentication setup”).
          </p>
        </Screen>
      )
    case 'error':
      return (
        <Screen title="Sign-in problem">
          <p role="alert" className={styles.alert}>
            {auth.message ?? 'Sign-in failed.'}
          </p>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={auth.signIn}>
              Try again
            </button>
          </div>
        </Screen>
      )
    case 'signed_out':
      return (
        <Screen title="Sign in to AegisAI">
          {auth.message && (
            <p role="alert" className={styles.alert}>
              {auth.message}
            </p>
          )}
          <p className={styles.text}>You need to sign in to use the Copilot.</p>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={auth.signIn}>
              Sign in
            </button>
          </div>
        </Screen>
      )
    case 'signed_in':
      return <AccountCheck auth={auth}>{children}</AccountCheck>
  }
}

function AccountCheck({ auth, children }: { auth: AuthState; children: ReactNode }) {
  const subject = auth.user?.subject ?? ''
  const [attempt, setAttempt] = useState(0)
  const key = `${subject}:${attempt}`
  // Keyed by who asked, so a result for a previous user or attempt never shows.
  const [result, setResult] = useState<{ key: string; check: Check } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getMe(controller.signal)
      .then((account) => setResult({ key, check: { kind: 'ok', account } }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof BackendError && error.statusCode === 403) {
          setResult({ key, check: { kind: 'not_provisioned' } })
        } else if (error instanceof BackendError && error.statusCode === 401) {
          // The API client has already told the auth layer; the gate re-renders as signed out.
        } else {
          setResult({ key, check: { kind: 'failed', message: friendlyMessage(error) } })
        }
      })
    return () => controller.abort()
  }, [key])

  const check = result?.key === key ? result.check : null

  if (check === null) {
    return (
      <Screen title="Signing in…">
        <p role="status" className={styles.text}>
          Checking your account.
        </p>
      </Screen>
    )
  }
  if (check.kind === 'ok') {
    // The app decides which administrator-only screens to show from this account's role.
    return <AccountContext.Provider value={check.account}>{children}</AccountContext.Provider>
  }
  if (check.kind === 'failed') {
    return (
      <Screen title="Could not check your account">
        <p role="alert" className={styles.alert}>
          {check.message}
        </p>
        <div className={styles.actions}>
          <button type="button" className={styles.primary} onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
          <button type="button" className={styles.secondary} onClick={auth.signOut}>
            Sign out
          </button>
        </div>
      </Screen>
    )
  }
  return (
    <Screen title="Your account is not set up yet">
      <p role="alert" className={styles.alert}>
        You are signed in, but no AegisAI account is linked to this identity.
      </p>
      <p className={styles.text}>
        Ask an administrator to link it (they need the values below), then sign in again.
      </p>
      <dl className={styles.details}>
        {auth.user?.email && (
          <>
            <dt>Email</dt>
            <dd>{auth.user.email}</dd>
          </>
        )}
        <dt>Subject</dt>
        <dd>
          <code>{auth.user?.subject}</code>
        </dd>
        <dt>Issuer</dt>
        <dd>
          <code>{auth.user?.issuer}</code>
        </dd>
      </dl>
      <div className={styles.actions}>
        <button type="button" className={styles.secondary} onClick={auth.signOut}>
          Sign out
        </button>
      </div>
    </Screen>
  )
}
