import { useState } from 'react'
import type { MultiAgentRunResult } from '../../api/copilot'
import { Icon } from '../Icon'
import styles from './WorkflowDetails.module.css'

const STATUS_LABEL: Record<string, string> = {
  completed: 'Completed',
  partial: 'Partial — some agents did not complete',
  failed: 'Failed',
  timeout: 'Timed out',
}

function renderSource(source: Record<string, unknown>, index: number) {
  if ('expression' in source) {
    const success = source.success as boolean
    return (
      <li key={index} className={styles.sourceItem}>
        <span className={success ? styles.ok : styles.fail}>{success ? '✓' : '✗'}</span>
        <code>{String(source.expression)}</code> = {String(source.result ?? '—')}
      </li>
    )
  }
  const filename = (source.filename as string) ?? 'Document'
  const page = source.page_number as number | undefined
  const similarity = source.similarity as number | undefined
  const agentName = source.agent_name as string | undefined
  return (
    <li key={index} className={styles.sourceItem}>
      <Icon name="documents" size={16} />
      <div>
        <div>
          {filename}
          {page !== undefined && page !== null ? ` · page ${page}` : ''}
        </div>
        <div className={styles.sourceMeta}>
          {similarity !== undefined && `similarity ${similarity.toFixed(2)}`}
          {agentName && ` · via ${agentName}`}
        </div>
      </div>
    </li>
  )
}

export function WorkflowDetails({ result }: { result: MultiAgentRunResult }) {
  const [open, setOpen] = useState(false)
  const label = STATUS_LABEL[result.status] ?? result.status

  return (
    <div className={styles.container}>
      <button type="button" className={styles.toggle} onClick={() => setOpen((o) => !o)}>
        <Icon name={open ? 'chevron-left' : 'chevron-right'} size={14} />
        Workflow details
        <span className={styles.statusPill}>{label}</span>
      </button>

      {open && (
        <div className={styles.panel}>
          {result.agents_used.map((agent) => (
            <div key={agent.agent_name} className={styles.agentRow}>
              <span className={styles.agentName}>{agent.agent_name}</span>
              <span className={styles.agentStatus}>{agent.status}</span>
              <span className={styles.agentDuration}>{agent.duration_ms.toFixed(0)} ms</span>
              {agent.retry_count > 0 && (
                <span className={styles.retryBadge}>retried {agent.retry_count}×</span>
              )}
              {agent.error && <div className={styles.agentError}>{agent.error}</div>}
            </div>
          ))}

          {result.sources.length > 0 && (
            <div className={styles.sources}>
              <div className={styles.sourcesTitle}>Sources ({result.sources.length})</div>
              <ul className={styles.sourceList}>
                {result.sources.map((source, index) => renderSource(source, index))}
              </ul>
            </div>
          )}

          <div className={styles.footer}>
            Duration: {result.duration_ms.toFixed(0)} ms · workflow{' '}
            <code>{result.workflow_id}</code>
          </div>
        </div>
      )}
    </div>
  )
}
