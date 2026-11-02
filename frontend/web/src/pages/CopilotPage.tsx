import { useEffect, useRef, useState } from 'react'
import { Composer } from '../components/Chat/Composer'
import { MessageBubble } from '../components/Chat/MessageBubble'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { getConversation } from '../api/conversations'
import { runMultiAgentWorkflow } from '../api/copilot'
import { streamAgentRun, streamPlainChat, streamRagChat } from '../api/stream'
import type { StreamRequest } from '../api/stream'
import type { ChatTurn, ToolStep } from '../types/chat'
import { friendlyMessage } from '../utils/errors'
import styles from './CopilotPage.module.css'

type Mode = 'stream' | 'chat' | 'agent' | 'workflow'

const SUBTITLE: Record<Mode, string> = {
  stream:
    'Ask a question about your documents — the answer appears as it is written, with its sources.',
  chat: 'Chat with the model directly. It does not search your documents.',
  agent:
    'The agent can search your documents, calculate and use its other tools. You see each tool it uses.',
  workflow:
    'Ask a question — the Copilot decides whether it needs the Research, Document, or Analyst agent to answer it.',
}

function makeId(): string {
  return Math.random().toString(36).slice(2)
}

function isAbort(error: unknown): boolean {
  // DOMException is not always an `Error` instance across realms (jsdom), so check the name.
  return typeof error === 'object' && error !== null && (error as { name?: string }).name === 'AbortError'
}

export function CopilotPage({ initialConversationId }: { initialConversationId?: string }) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [sending, setSending] = useState(false)
  const [mode, setMode] = useState<Mode>('stream')
  const [loadingConversation, setLoadingConversation] = useState(Boolean(initialConversationId))
  const [loadError, setLoadError] = useState<string | null>(null)
  const conversationId = useRef<string | null>(null)
  const controller = useRef<AbortController | null>(null)

  // Leaving the page cancels an answer that is still arriving.
  useEffect(() => () => controller.current?.abort(), [])

  // Continuing a saved conversation: load its messages, then keep sending to the same id.
  useEffect(() => {
    if (!initialConversationId) return
    const abort = new AbortController()
    getConversation(initialConversationId, abort.signal)
      .then((conversation) => {
        conversationId.current = conversation.id
        setTurns(
          conversation.messages
            .filter((message) => message.role === 'user' || message.role === 'assistant')
            .map((message) => ({
              id: message.id,
              role: message.role as 'user' | 'assistant',
              content: message.content,
            })),
        )
        setLoadingConversation(false)
      })
      .catch((error) => {
        if (isAbort(error)) return
        setLoadError(friendlyMessage(error))
        setLoadingConversation(false)
      })
    return () => abort.abort()
  }, [initialConversationId])

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

  /** Runs one request with its own AbortController, mapping every ending onto the answer turn. */
  async function run(
    message: string,
    answerId: string,
    execute: (signal: AbortSignal) => Promise<void>,
  ) {
    const abort = new AbortController()
    controller.current = abort
    try {
      await execute(abort.signal)
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

  function chatStream(
    stream: (request: StreamRequest) => Promise<void>,
    message: string,
    answerId: string,
  ) {
    return run(message, answerId, (signal) =>
      stream({
        message,
        conversationId: conversationId.current,
        signal,
        onChunk: (chunk) => {
          if (chunk.conversation_id) conversationId.current = chunk.conversation_id
          patchTurn(answerId, (turn) => ({
            content: turn.content + chunk.delta,
            ...(chunk.is_final && chunk.sources ? { sources: chunk.sources } : {}),
          }))
        },
      }),
    )
  }

  function agentStream(message: string, answerId: string) {
    return run(message, answerId, (signal) =>
      streamAgentRun({
        message,
        conversationId: conversationId.current,
        signal,
        onEvent: (event) => {
          if (event.type === 'tool_started') {
            patchTurn(answerId, (turn) => ({
              toolSteps: [
                ...(turn.toolSteps ?? []),
                { name: event.toolName, status: 'running' } as ToolStep,
              ],
            }))
          } else if (event.type === 'tool_completed') {
            patchTurn(answerId, (turn) => {
              const steps = [...(turn.toolSteps ?? [])]
              const index = steps.findIndex(
                (step) => step.name === event.toolName && step.status === 'running',
              )
              const finished: ToolStep = {
                name: event.toolName,
                status: event.success ? 'succeeded' : 'failed',
              }
              if (index === -1) steps.push(finished)
              else steps[index] = finished
              return { toolSteps: steps }
            })
          } else if (event.type === 'answer_delta') {
            patchTurn(answerId, (turn) => ({ content: turn.content + event.delta }))
          } else if (event.conversationId) {
            conversationId.current = event.conversationId
          }
        },
      }),
    )
  }

  function workflow(message: string, answerId: string) {
    return run(message, answerId, async (signal) => {
      const result = await runMultiAgentWorkflow(message, signal)
      patchTurn(answerId, { content: result.answer, result })
    })
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
      if (mode === 'stream') await chatStream(streamRagChat, message, answerId)
      else if (mode === 'chat') await chatStream(streamPlainChat, message, answerId)
      else if (mode === 'agent') await agentStream(message, answerId)
      else await workflow(message, answerId)
    } finally {
      setSending(false)
    }
  }

  function newConversation() {
    controller.current?.abort()
    conversationId.current = null
    setLoadError(null)
    setTurns([])
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <p className={styles.subtitle}>{SUBTITLE[mode]}</p>
        <div className={styles.controls}>
          <select
            className={styles.mode}
            aria-label="Answer mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as Mode)}
            disabled={sending}
          >
            <option value="stream">Streamed answer</option>
            <option value="chat">Plain chat</option>
            <option value="agent">Agent</option>
            <option value="workflow">Multi-agent workflow</option>
          </select>
          <button
            type="button"
            className={styles.newConversation}
            onClick={newConversation}
            disabled={turns.length === 0 && !loadError}
          >
            <Icon name="plus" size={16} />
            New conversation
          </button>
        </div>
      </div>

      <div className={styles.transcript}>
        {loadingConversation ? (
          <p role="status" className={styles.subtitle}>
            Loading conversation…
          </p>
        ) : loadError ? (
          <EmptyState title="Could not open that conversation" description={loadError} />
        ) : turns.length === 0 ? (
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
      <Composer onSend={(message) => void send(message)} disabled={sending || loadingConversation} />
    </div>
  )
}
