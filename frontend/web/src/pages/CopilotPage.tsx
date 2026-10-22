import { useEffect, useRef, useState } from 'react'
import { Composer } from '../components/Chat/Composer'
import { MessageBubble } from '../components/Chat/MessageBubble'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { runMultiAgentWorkflow } from '../api/copilot'
import { streamRagChat } from '../api/stream'
import type { ChatTurn } from '../types/chat'
import { friendlyMessage } from '../utils/errors'
import styles from './CopilotPage.module.css'

type Mode = 'stream' | 'workflow'

function makeId(): string {
  return Math.random().toString(36).slice(2)
}

function isAbort(error: unknown): boolean {
  // DOMException is not always an `Error` instance across realms (jsdom), so check the name.
  return typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError'
}

export function CopilotPage() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [sending, setSending] = useState(false)
  const [mode, setMode] = useState<Mode>('stream')
  const conversationId = useRef<string | null>(null)
  const controller = useRef<AbortController | null>(null)

  // Leaving the page cancels an answer that is still arriving.
  useEffect(() => () => controller.current?.abort(), [])

  function patchTurn(
    id: string,
    patch: Partial<ChatTurn> | ((turn: ChatTurn) => Partial<ChatTurn>),
  ) {
    setTurns((prev) =>
      prev.map((turn) =>
        turn.id === id ? { ...turn, ...(typeof patch === 'function' ? patch(turn) : patch) } : turn,
      ),
    )
  }

  async function runStreamed(message: string, answerId: string) {
    const abort = new AbortController()
    controller.current = abort
    try {
      await streamRagChat({
        message,
        conversationId: conversationId.current,
        signal: abort.signal,
        onChunk: (chunk) => {
          if (chunk.conversation_id) conversationId.current = chunk.conversation_id
          patchTurn(answerId, (turn) => ({
            content: turn.content + chunk.delta,
            ...(chunk.is_final ? { sources: chunk.sources ?? [] } : {}),
          }))
        },
      })
      patchTurn(answerId, { streaming: false })
    } catch (error) {
      if (isAbort(error)) {
        // Stopped by the user (or the page closing): keep what arrived and say so.
        patchTurn(answerId, { streaming: false, stopped: true })
      } else {
        // Partial text from a broken stream stays visible, with the error beneath it.
        patchTurn(answerId, {
          streaming: false,
          error: friendlyMessage(error),
          retryMessage: message,
        })
      }
    } finally {
      if (controller.current === abort) controller.current = null
    }
  }

  async function runWorkflow(message: string, answerId: string) {
    const abort = new AbortController()
    controller.current = abort
    try {
      const result = await runMultiAgentWorkflow(message, abort.signal)
      patchTurn(answerId, { streaming: false, content: result.answer, result })
    } catch (error) {
      if (isAbort(error)) {
        patchTurn(answerId, { streaming: false, stopped: true })
      } else {
        patchTurn(answerId, {
          streaming: false,
          error: friendlyMessage(error),
          retryMessage: message,
        })
      }
    } finally {
      if (controller.current === abort) controller.current = null
    }
  }

  async function send(message: string, replaceTurnId?: string) {
    const answerId = makeId()
    const answer: ChatTurn = { id: answerId, role: 'assistant', content: '', streaming: true }
    setSending(true)
    setTurns((prev) =>
      replaceTurnId
        ? // A retry replaces the failed answer; the user's message is already in the transcript.
          prev.map((turn) => (turn.id === replaceTurnId ? answer : turn))
        : [...prev, { id: makeId(), role: 'user', content: message }, answer],
    )
    try {
      await (mode === 'stream' ? runStreamed(message, answerId) : runWorkflow(message, answerId))
    } finally {
      setSending(false)
    }
  }

  function newConversation() {
    controller.current?.abort()
    conversationId.current = null
    setTurns([])
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <p className={styles.subtitle}>
          {mode === 'stream'
            ? 'Ask a question about your documents — the answer appears as it is written, with its sources.'
            : 'Ask a question — the Copilot decides whether it needs the Research, Document, or Analyst agent to answer it.'}
        </p>
        <div className={styles.controls}>
          <select
            className={styles.mode}
            aria-label="Answer mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as Mode)}
            disabled={sending}
          >
            <option value="stream">Streamed answer</option>
            <option value="workflow">Multi-agent workflow</option>
          </select>
          <button
            type="button"
            className={styles.newConversation}
            onClick={newConversation}
            disabled={turns.length === 0}
          >
            <Icon name="plus" size={16} />
            New conversation
          </button>
        </div>
      </div>

      <div className={styles.transcript}>
        {turns.length === 0 ? (
          <EmptyState
            title="No messages yet"
            description="Ask about a policy, a document (paste its id from the Documents page), or a calculation."
          />
        ) : (
          turns.map((turn) => (
            <MessageBubble
              key={turn.id}
              turn={turn}
              onRetry={
                turn.error && turn.retryMessage && !sending
                  ? () => void send(turn.retryMessage as string, turn.id)
                  : undefined
              }
            />
          ))
        )}
      </div>

      {sending && (
        <div className={styles.stopRow}>
          <button type="button" className={styles.stop} onClick={() => controller.current?.abort()}>
            Stop generating
          </button>
        </div>
      )}
      <Composer onSend={(message) => void send(message)} disabled={sending} />
    </div>
  )
}
