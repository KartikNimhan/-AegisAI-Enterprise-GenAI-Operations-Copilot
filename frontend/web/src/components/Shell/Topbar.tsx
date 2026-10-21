import { useOptionalAuthState } from '../../auth/AuthContext'
import { useBackendHealth } from '../../hooks/useBackendHealth'
import { StatusBadge, toneFromCheck } from '../StatusBadge'
import styles from './Topbar.module.css'

export function Topbar({ title }: { title: string }) {
  const isUp = useBackendHealth()
  const auth = useOptionalAuthState()

  return (
    <header className={styles.topbar}>
      <h1 className={styles.title}>{title}</h1>
      <div className={styles.right}>
        {isUp === null ? (
          <StatusBadge tone="unknown" label="Connecting…" />
        ) : (
          <StatusBadge
            tone={toneFromCheck(isUp)}
            label={isUp ? 'Backend connected' : 'Backend unreachable'}
          />
        )}
        {auth?.status === 'signed_in' && auth.user && (
          <>
            <span className={styles.user}>{auth.user.email ?? auth.user.name ?? auth.user.subject}</span>
            <button type="button" className={styles.signOut} onClick={auth.signOut}>
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  )
}
