import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { Icon } from '../components/Icon'
import { StatusBadge } from '../components/StatusBadge'
import { toneFromCheck, type StatusTone } from '../components/statusTone'
import { getSystemStatus, type SystemStatus } from '../api/system'
import { friendlyMessage } from '../utils/errors'
import styles from './SystemStatusPage.module.css'

export function SystemStatusPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const next = await getSystemStatus()
      setStatus(next)
      setError(null)
    } catch (err) {
      setError(friendlyMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  // The first load handles its result in promise callbacks (no synchronous state change in the
  // effect); later loads come from the Refresh button.
  useEffect(() => {
    let active = true
    getSystemStatus()
      .then((next) => {
        if (active) setStatus(next)
      })
      .catch((err) => {
        if (active) setError(friendlyMessage(err))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  function refresh() {
    setLoading(true)
    setError(null)
    void load()
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h2 className={styles.title}>Dependencies</h2>
        <button type="button" className={styles.refresh} onClick={refresh} disabled={loading}>
          <Icon name="refresh" size={14} />
          Refresh
        </button>
      </div>

      {error && (
        <p role="alert" className={styles.error}>
          <Icon name="alert" size={14} /> {error}
        </p>
      )}

      <Card className={styles.card}>
        <Row label="Database (PostgreSQL)" tone={status ? toneFromCheck(status.database) : 'unknown'} />
        <Row label="Redis" tone={status ? toneFromCheck(status.redis) : 'unknown'} />
      </Card>

      <h2 className={styles.title}>Configuration</h2>
      <Card className={styles.card}>
        <Row
          label="LLM provider (Groq) configured"
          tone={status ? toneFromCheck(status.llm_configured) : 'unknown'}
        />
        <div className={styles.configRow}>
          <span className={styles.configLabel}>MCP server</span>
          <span className={styles.configValue}>{status?.mcp_server || '—'}</span>
        </div>
        <div className={styles.configRow}>
          <span className={styles.configLabel}>Trusted A2A agents</span>
          <span className={styles.configValue}>
            {status?.trusted_a2a_agents?.length ? status.trusted_a2a_agents.join(', ') : '—'}
          </span>
        </div>
      </Card>

      <p className={styles.note}>
        Database and Redis are live connectivity checks. LLM/MCP/A2A rows reflect configuration,
        not a live provider call.
      </p>
    </div>
  )
}

function Row({ label, tone }: { label: string; tone: StatusTone }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <StatusBadge tone={tone} />
    </div>
  )
}
