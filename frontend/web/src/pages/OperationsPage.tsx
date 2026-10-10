import { useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { getOperationsSummary, type OperationsSummary } from '../api/operations'
import { friendlyMessage } from '../utils/errors'
import styles from './OperationsPage.module.css'

const STATUS_LABEL: Record<string, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  processed: 'Processed',
  failed: 'Failed',
}

export function OperationsPage() {
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getOperationsSummary()
      .then(setSummary)
      .catch((err) => setError(friendlyMessage(err)))
  }, [])

  if (error) {
    return (
      <Card>
        <EmptyState title="Could not load operations data" description={error} />
      </Card>
    )
  }

  if (!summary) {
    return (
      <Card>
        <div className={styles.loading}>Loading…</div>
      </Card>
    )
  }

  const statusEntries = Object.entries(summary.documents_by_status)
  const maxCount = Math.max(1, ...statusEntries.map(([, count]) => count))

  return (
    <div className={styles.page}>
      <Card className={styles.totalCard}>
        <span className={styles.totalLabel}>Total documents</span>
        <span className={styles.totalValue}>{summary.total_documents}</span>
      </Card>

      <Card className={styles.breakdownCard}>
        <h2 className={styles.sectionTitle}>Documents by status</h2>
        {statusEntries.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload documents from the Documents page to see a breakdown here."
          />
        ) : (
          <div className={styles.bars}>
            {statusEntries.map(([status, count]) => (
              <div key={status} className={styles.barRow}>
                <span className={styles.barLabel}>{STATUS_LABEL[status] ?? status}</span>
                <div className={styles.barTrack}>
                  <div
                    className={`${styles.barFill} ${styles[status] ?? ''}`}
                    style={{ width: `${(count / maxCount) * 100}%` }}
                  />
                </div>
                <span className={styles.barValue}>{count}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <p className={styles.note}>
        <Icon name="alert" size={14} /> These numbers reflect only what the backend has
        persisted — no external monitoring or alerting is connected yet.
      </p>
    </div>
  )
}
