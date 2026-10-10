import { useState } from 'react'
import { Composer } from '../components/Chat/Composer'
import { MessageBubble } from '../components/Chat/MessageBubble'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { runMultiAgentWorkflow } from '../api/copilot'
import type { ChatTurn } from '../types/chat'
import { friendlyMessage } from '../utils/errors'
import styles from './CopilotPage.module.css'

function makeId(): string {
  return Math.random().toString(36).slice(2)
}

export function CopilotPage() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [sending, setSending] = useState(false)

  async function handleSend(message: string) {
    const userTurn: ChatTurn = { id: makeId(), role: 'user', content: message }
    setTurns((prev) => [...prev, userTurn])
    setSending(true)

    try {
      const result = await runMultiAgentWorkflow(message)
      setTurns((prev) => [
        ...prev,
        { id: makeId(), role: 'assistant', content: result.answer, result },
      ])
    } catch (error) {
      setTurns((prev) => [
        ...prev,
        { id: makeId(), role: 'assistant', content: '', error: friendlyMessage(error) },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <p className={styles.subtitle}>
          Ask a question — the Copilot decides whether it needs the Research, Document, or
          Analyst agent to answer it.
        </p>
        <button
          type="button"
          className={styles.newConversation}
          onClick={() => setTurns([])}
          disabled={turns.length === 0}
        >
          <Icon name="plus" size={16} />
          New conversation
        </button>
      </div>

      <div className={styles.transcript}>
        {turns.length === 0 ? (
          <EmptyState
            title="No messages yet"
            description="Ask about a policy, a document (paste its id from the Documents page), or a calculation."
          />
        ) : (
          turns.map((turn) => <MessageBubble key={turn.id} turn={turn} />)
        )}
        {sending && (
          <div className={styles.typing}>
            <span className={styles.dot} />
            <span className={styles.dot} />
            <span className={styles.dot} />
          </div>
        )}
      </div>

      <Composer onSend={handleSend} disabled={sending} />
    </div>
  )
}
