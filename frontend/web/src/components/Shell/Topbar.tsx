import { useOptionalAuthState } from '../../auth/AuthContext'
import { useBackendHealth } from '../../hooks/useBackendHealth'
import { Icon } from '../Icon'
import { ThemeSwitch } from '../../theme/ThemeSwitch'
import { StatusBadge } from '../StatusBadge'
import { toneFromCheck } from '../statusTone'
import styles from './Topbar.module.css'

export function Topbar({
  title,
  onMenu,
  menuOpen = false,
  menuControls,
  menuId,
}: {
  title: string
  /** Opens the navigation drawer (the button is shown below 768 px only). While the drawer is
   * open the top bar is inert, so the drawer's own Close button closes it. */
  onMenu?: () => void
  menuOpen?: boolean
  menuControls?: string
  menuId?: string
}) {
  const isUp = useBackendHealth()
  const auth = useOptionalAuthState()

  return (
    <header className={styles.topbar}>
      <div className={styles.left}>
        {onMenu && (
          <button
            type="button"
            id={menuId}
            className={styles.menu}
            onClick={onMenu}
            aria-expanded={menuOpen}
            aria-controls={menuControls}
            aria-label="Open navigation"
          >
            <Icon name="menu" size={20} />
          </button>
        )}
        <h1 className={styles.title}>{title}</h1>
      </div>
      <div className={styles.right}>
        <ThemeSwitch />
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
