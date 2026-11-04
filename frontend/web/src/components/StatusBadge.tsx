import styles from './StatusBadge.module.css'
import type { StatusTone } from './statusTone'

const TONE_LABEL: Record<StatusTone, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
  unknown: 'Unknown',
}

export function StatusBadge({ tone, label }: { tone: StatusTone; label?: string }) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <span className={styles.dot} />
      {label ?? TONE_LABEL[tone]}
    </span>
  )
}
