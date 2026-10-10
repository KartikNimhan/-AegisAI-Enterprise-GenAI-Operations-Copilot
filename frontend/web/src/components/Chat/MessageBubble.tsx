import type { ChatTurn } from '../../types/chat'
import { WorkflowDetails } from './WorkflowDetails'
import styles from './MessageBubble.module.css'

const WORKFLOW_NOTE: Record<string, string> = {
  partial: 'Partial answer — some agents did not complete.',
  failed: 'This request could not be completed.',
  timeout: 'This request timed out.',
}

export function MessageBubble({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user'

  return (
    <div className={`${styles.row} ${isUser ? styles.userRow : styles.assistantRow}`}>
      <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}>
        {turn.error ? (
          <p className={styles.errorText}>{turn.error}</p>
        ) : (
          <>
            <p className={styles.content}>
              {turn.content || (turn.result && 'No answer was produced for this request.')}
            </p>
            {turn.result && turn.result.status !== 'completed' && (
              <p className={styles.note}>{WORKFLOW_NOTE[turn.result.status] ?? turn.result.status}</p>
            )}
            {turn.result && turn.result.agents_used.length > 0 && (
              <WorkflowDetails result={turn.result} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
