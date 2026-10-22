import type { ChatTurn } from '../../types/chat'
import { WorkflowDetails } from './WorkflowDetails'
import styles from './MessageBubble.module.css'

const WORKFLOW_NOTE: Record<string, string> = {
  partial: 'Partial answer — some agents did not complete.',
  failed: 'This request could not be completed.',
  timeout: 'This request timed out.',
}

export function MessageBubble({ turn, onRetry }: { turn: ChatTurn; onRetry?: () => void }) {
  const isUser = turn.role === 'user'
  const waiting = turn.streaming && !turn.content

  return (
    <div className={`${styles.row} ${isUser ? styles.userRow : styles.assistantRow}`}>
      <div
        className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}
        aria-busy={turn.streaming ? true : undefined}
      >
        {waiting ? (
          <p className={styles.note} role="status">
            Thinking…
          </p>
        ) : (
          <>
            {/* Text that arrived before a failure or a stop stays visible. */}
            {(turn.content || (!turn.error && !turn.stopped && turn.result)) && (
              <p className={styles.content}>
                {turn.content || 'No answer was produced for this request.'}
                {turn.streaming && <span className={styles.cursor} aria-hidden="true" />}
              </p>
            )}
            {turn.stopped && <p className={styles.note}>Stopped.</p>}
            {turn.error && (
              <p className={styles.errorText} role="alert">
                {turn.error}
              </p>
            )}
            {turn.error && onRetry && (
              <button type="button" className={styles.retry} onClick={onRetry}>
                Try again
              </button>
            )}
            {turn.result && turn.result.status !== 'completed' && (
              <p className={styles.note}>{WORKFLOW_NOTE[turn.result.status] ?? turn.result.status}</p>
            )}
            {turn.result && turn.result.agents_used.length > 0 && (
              <WorkflowDetails result={turn.result} />
            )}
            {turn.sources && turn.sources.length > 0 && (
              <ul className={styles.sources} aria-label="Sources">
                {turn.sources.map((source) => (
                  <li key={source.source_id} className={source.cited ? styles.cited : undefined}>
                    [{source.source_id}] {source.filename}
                    {source.page !== null ? ` · page ${source.page}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  )
}
