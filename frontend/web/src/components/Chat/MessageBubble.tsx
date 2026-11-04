import type { ChatTurn, SourceRef } from '../../types/chat'
import { MessageText } from './MessageText'
import { WorkflowDetails } from './WorkflowDetails'
import styles from './MessageBubble.module.css'

const WORKFLOW_NOTE: Record<string, string> = {
  partial: 'Partial answer — some agents did not complete.',
  failed: 'This request could not be completed.',
  timeout: 'This request timed out.',
}

const STEP_LABEL = { running: 'running', succeeded: 'done', failed: 'failed' } as const

function SourceItem({ source, onOpen }: { source: SourceRef; onOpen?: (sourceId: string) => void }) {
  const unavailable = source.status === 'unavailable'
  return (
    <li className={source.cited ? styles.cited : undefined}>
      <span>
        [{source.source_id}]{' '}
        {unavailable ? (
          <span className={styles.sourceUnavailable}>Source no longer available</span>
        ) : (
          <>
            {source.filename}
            {source.page !== null ? ` · page ${source.page}` : ''}
          </>
        )}
      </span>
      {onOpen && (
        <button
          type="button"
          className={styles.viewSource}
          onClick={() => onOpen(source.source_id)}
          aria-label={`View source ${source.source_id}`}
        >
          View
        </button>
      )}
    </li>
  )
}

export function MessageBubble({
  turn,
  onRetry,
  onOpenCitation,
}: {
  turn: ChatTurn
  onRetry?: () => void
  /** Opens a source of this (saved) answer in the citation panel. */
  onOpenCitation?: (sourceId: string) => void
}) {
  const isUser = turn.role === 'user'
  const waiting = turn.streaming && !turn.content
  const sourceIds = new Set((turn.sources ?? []).map((source) => source.source_id))
  const toolSteps =
    turn.toolSteps && turn.toolSteps.length > 0 ? (
      <ul className={styles.toolSteps} aria-label="Tools used">
        {turn.toolSteps.map((step, index) => (
          <li key={`${step.name}-${index}`} className={styles[step.status]}>
            {step.name}
            <span className={styles.stepStatus}> — {STEP_LABEL[step.status]}</span>
          </li>
        ))}
      </ul>
    ) : null

  return (
    <div className={`${styles.row} ${isUser ? styles.userRow : styles.assistantRow}`}>
      <div
        className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}
        aria-busy={turn.streaming ? true : undefined}
      >
        {waiting ? (
          <>
            <output className={styles.note}>Thinking…</output>
            {toolSteps}
          </>
        ) : (
          <>
            {/* Text that arrived before a failure or a stop stays visible. */}
            {(turn.content || (!turn.error && !turn.stopped && turn.result)) && (
              <div className={styles.content}>
                {isUser ? (
                  <p className={styles.plain}>{turn.content}</p>
                ) : (
                  <MessageText
                    text={turn.content || 'No answer was produced for this request.'}
                    sourceIds={sourceIds}
                    onCitation={turn.streaming ? undefined : onOpenCitation}
                    trailing={
                      turn.streaming ? <span className={styles.cursor} aria-hidden="true" /> : undefined
                    }
                  />
                )}
              </div>
            )}
            {toolSteps}
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
              <>
                <ul className={styles.sources} aria-label="Sources">
                  {turn.sources.map((source) => (
                    <SourceItem
                      key={source.source_id}
                      source={source}
                      onOpen={turn.streaming ? undefined : onOpenCitation}
                    />
                  ))}
                </ul>
                <p className={styles.sourceNote}>Retrieved sources — support not verified.</p>
              </>
            )}
            {turn.invalidCitations && turn.invalidCitations.length > 0 && (
              <p className={styles.note}>
                The model cited {turn.invalidCitations.join(', ')}, which{' '}
                {turn.invalidCitations.length === 1 ? 'was' : 'were'} not among the retrieved
                sources; {turn.invalidCitations.length === 1 ? 'it was' : 'they were'} removed.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
