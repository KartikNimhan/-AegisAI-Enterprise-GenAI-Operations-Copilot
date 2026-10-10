import styles from './StatusPill.module.css'

const LABEL: Record<string, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  processed: 'Processed',
  failed: 'Failed',
}

const TONE: Record<string, string> = {
  uploaded: 'neutral',
  processing: 'pending',
  processed: 'ok',
  failed: 'danger',
}

export function StatusPill({ status }: { status: string }) {
  const tone = TONE[status] ?? 'neutral'
  return <span className={`${styles.pill} ${styles[tone]}`}>{LABEL[status] ?? status}</span>
}
