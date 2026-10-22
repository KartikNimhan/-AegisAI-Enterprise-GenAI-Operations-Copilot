import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import {
  clearMemories,
  createMemory,
  deleteMemory,
  listMemories,
  updateMemory,
  type Memory,
  type MemoryKind,
} from '../api/memories'
import { friendlyMessage } from '../utils/errors'
import styles from './ListPages.module.css'

const MAX_NOTE_CHARS = 500 // AGENT_MEMORY_MAX_ITEM_CHARS default; the server is the authority

export function MemoryPage() {
  const [items, setItems] = useState<Memory[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [kind, setKind] = useState<MemoryKind>('fact')
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [confirming, setConfirming] = useState<string | 'all' | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    listMemories()
      .then(setItems)
      .catch((err) => setError(friendlyMessage(err)))
  }, [])

  // The first load happens from the effect; no state is set synchronously here.
  useEffect(load, [load])

  function retry() {
    setError(null)
    load()
  }

  async function guarded(action: () => Promise<void>) {
    setBusy(true)
    setActionError(null)
    setNotice(null)
    try {
      await action()
    } catch (err) {
      // e.g. 409 "memory is full" or 422 "cannot contain control characters": the server's words.
      setActionError(friendlyMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function add(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content) return
    void guarded(async () => {
      const saved = await createMemory(content, kind)
      setItems((prev) => [saved, ...(prev ?? []).filter((item) => item.id !== saved.id)])
      setDraft('')
    })
  }

  function saveEdit(id: string) {
    const content = editText.trim()
    if (!content) return
    void guarded(async () => {
      const saved = await updateMemory(id, content)
      setItems((prev) => (prev ? prev.map((item) => (item.id === id ? saved : item)) : prev))
      setEditing(null)
    })
  }

  function remove(id: string) {
    void guarded(async () => {
      await deleteMemory(id)
      setItems((prev) => (prev ? prev.filter((item) => item.id !== id) : prev))
      setConfirming(null)
    })
  }

  function forgetAll() {
    void guarded(async () => {
      const deleted = await clearMemories()
      setItems([])
      setConfirming(null)
      setNotice(`Forgot ${deleted} ${deleted === 1 ? 'note' : 'notes'}.`)
    })
  }

  if (error && !items) {
    return (
      <Card>
        <EmptyState
          title="Could not load your memory"
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

  return (
    <div className={styles.page}>
      <Card className={styles.detail}>
        <p className={styles.meta}>
          Notes the agent keeps about you between conversations. Anything it saves while reading
          documents is untrusted, so review it here. You can edit or delete any note.
        </p>
        <form className={styles.form} onSubmit={add}>
          <label className={styles.label} htmlFor="memory-content">
            New note
          </label>
          <textarea
            id="memory-content"
            className={styles.input}
            value={draft}
            maxLength={MAX_NOTE_CHARS}
            rows={2}
            onChange={(event) => setDraft(event.target.value)}
            disabled={busy}
          />
          <div className={styles.formRow}>
            <select
              className={styles.select}
              aria-label="Kind"
              value={kind}
              onChange={(event) => setKind(event.target.value as MemoryKind)}
              disabled={busy}
            >
              <option value="fact">Fact</option>
              <option value="preference">Preference</option>
            </select>
            <button type="submit" className={styles.button} disabled={busy || !draft.trim()}>
              Save note
            </button>
          </div>
        </form>
      </Card>

      {actionError && (
        <p className={styles.error} role="alert">
          {actionError}
        </p>
      )}
      {notice && (
        <p className={styles.meta} role="status">
          {notice}
        </p>
      )}

      {items.length === 0 ? (
        <Card>
          <EmptyState
            title="Nothing remembered yet"
            description="Notes you add here, or that the agent saves for you, appear in this list."
          />
        </Card>
      ) : (
        <Card>
          <ul className={styles.list} aria-label="Memory notes">
            {items.map((item) => (
              <li key={item.id} className={styles.row}>
                {editing === item.id ? (
                  <div className={styles.main}>
                    <label className={styles.label} htmlFor={`edit-${item.id}`}>
                      Edit note
                    </label>
                    <textarea
                      id={`edit-${item.id}`}
                      className={styles.input}
                      value={editText}
                      maxLength={MAX_NOTE_CHARS}
                      rows={2}
                      onChange={(event) => setEditText(event.target.value)}
                      disabled={busy}
                    />
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.button}
                        disabled={busy || !editText.trim()}
                        onClick={() => saveEdit(item.id)}
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        className={styles.button}
                        disabled={busy}
                        onClick={() => setEditing(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className={styles.main}>
                      <span>{item.content}</span>
                      <span className={styles.meta}>
                        {item.kind} · {item.source === 'agent' ? 'saved by the agent' : 'added by you'}
                      </span>
                    </div>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.button}
                        onClick={() => {
                          setEditing(item.id)
                          setEditText(item.content)
                        }}
                        aria-label={`Edit note: ${item.content}`}
                      >
                        Edit
                      </button>
                      {confirming === item.id ? (
                        <>
                          <button
                            type="button"
                            className={styles.danger}
                            disabled={busy}
                            onClick={() => remove(item.id)}
                            aria-label={`Confirm delete note: ${item.content}`}
                          >
                            Confirm delete
                          </button>
                          <button
                            type="button"
                            className={styles.button}
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
                          aria-label={`Delete note: ${item.content}`}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
          <div className={styles.footer}>
            {confirming === 'all' ? (
              <>
                <span>Forget all {items.length} notes? This cannot be undone.</span>
                <button type="button" className={styles.danger} disabled={busy} onClick={forgetAll}>
                  Confirm forget all
                </button>
                <button type="button" className={styles.button} onClick={() => setConfirming(null)}>
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" className={styles.button} onClick={() => setConfirming('all')}>
                Forget everything
              </button>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
