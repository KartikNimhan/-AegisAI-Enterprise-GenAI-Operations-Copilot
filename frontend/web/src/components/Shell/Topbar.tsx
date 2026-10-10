import { useBackendHealth } from '../../hooks/useBackendHealth'
import { StatusBadge, toneFromCheck } from '../StatusBadge'
import styles from './Topbar.module.css'

export function Topbar({ title }: { title: string }) {
  const isUp = useBackendHealth()

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
      </div>
    </header>
  )
}
