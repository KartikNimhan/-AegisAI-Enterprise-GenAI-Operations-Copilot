import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import {
  deleteConversation,
  getConversation,
  listConversations,
  type ConversationDetail,
  type ConversationSummary,
} from '../api/conversations'
import { friendlyMessage } from '../utils/errors'
import styles from './ListPages.module.css'

function when(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

export function ConversationsPage() {
  const [items, setItems] = useState<ConversationSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [opened, setOpened] = useState<ConversationDetail | null>(null)
  const [openError, setOpenError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    listConversations()
      .then(setItems)
      .catch((err) => setError(friendlyMessage(err)))
  }, [])

  // The first load happens from the effect; no state is set synchronously here.
  useEffect(load, [load])

  function retry() {
    setError(null)
    load()
  }

  async function open(id: string) {
    setOpenError(null)
    try {
      setOpened(await getConversation(id))
    } catch (err) {
      setOpened(null)
      setOpenError(friendlyMessage(err))
    }
  }

  async function remove(id: string) {
    setBusy(true)
    try {
      await deleteConversation(id)
      setConfirming(null)
      if (opened?.id === id) setOpened(null)
      setItems((prev) => (prev ? prev.filter((item) => item.id !== id) : prev))
    } catch (err) {
      setError(friendlyMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (error && !items) {
    return (
      <Card>
        <EmptyState
          title="Could not load your conversations"
          description={error}
          action={
            <button type="button" className={styles.button} onClick={retry}>
              Try again
            </button>
          }
        />
      </Card>
    )
  }

  if (!items) {
    return (
      <Card>
        <div className={styles.loading} role="status">
          Loading…
        </div>
      </Card>
    )
  }

  if (items.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No conversations yet"
          description="Conversations you start in the Copilot are saved here."
          action={
            <Link className={styles.link} to="/">
              Open the Copilot
            </Link>
          }
        />
      </Card>
    )
  }

  return (
    <div className={styles.page}>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <Card>
        <ul className={styles.list} aria-label="Conversations">
          {items.map((item) => {
            const label = item.title || 'Untitled conversation'
            return (
              <li key={item.id} className={styles.row}>
                <div className={styles.main}>
                  <button
                    type="button"
                    className={styles.titleButton}
                    onClick={() => void open(item.id)}
                    aria-label={`Open ${label}`}
                  >
                    {label}
                  </button>
                  <span className={styles.meta}>Updated {when(item.updated_at)}</span>
                </div>
                <div className={styles.actions}>
                  <Link className={styles.link} to={`/?conversation=${item.id}`}>
                    Continue
                  </Link>
                  {confirming === item.id ? (
                    <>
                      <button
                        type="button"
                        className={styles.danger}
                        disabled={busy}
                        onClick={() => void remove(item.id)}
                        aria-label={`Confirm delete ${label}`}
                      >
                        Confirm delete
                      </button>
                      <button
                        type="button"
                        className={styles.button}
                        disabled={busy}
                        onClick={() => setConfirming(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => setConfirming(item.id)}
                      aria-label={`Delete ${label}`}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      {openError && (
        <p className={styles.error} role="alert">
          {openError}
        </p>
      )}
      {opened && (
        <Card className={styles.detail}>
          <h2 className={styles.heading}>{opened.title || 'Untitled conversation'}</h2>
          {opened.messages.length === 0 ? (
            <p className={styles.meta}>This conversation has no messages.</p>
          ) : (
            <ol className={styles.messages} aria-label="Messages">
              {opened.messages.map((message) => (
                <li key={message.id}>
                  <strong>{message.role === 'user' ? 'You' : 'Copilot'}:</strong> {message.content}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </div>
  )
}
