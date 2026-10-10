import styles from './StatusBadge.module.css'

export type StatusTone = 'healthy' | 'degraded' | 'unavailable' | 'unknown'

const TONE_LABEL: Record<StatusTone, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
  unknown: 'Unknown',
}

export function toneFromCheck(ok: string | boolean): StatusTone {
  if (typeof ok === 'boolean') return ok ? 'healthy' : 'unavailable'
  if (ok === 'ok') return 'healthy'
  if (ok === 'unavailable') return 'unavailable'
  return 'unknown'
}

export function StatusBadge({ tone, label }: { tone: StatusTone; label?: string }) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <span className={styles.dot} />
      {label ?? TONE_LABEL[tone]}
    </span>
  )
}
