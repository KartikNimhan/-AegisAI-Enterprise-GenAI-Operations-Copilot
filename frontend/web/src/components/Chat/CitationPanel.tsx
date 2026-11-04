/**
 * The citation source panel (M10.5).
 *
 * Opens one source of a saved answer and shows exactly the passage the model was given, read from
 * the backend, which re-checks the caller's CURRENT access on every request (M10.4). Nothing is
 * shown from memory: a source that has since been deleted or made private appears as unavailable,
 * with no file name, page or text.
 *
 * Evidence wording (M10 decision 6): a citation only shows that this passage was RETRIEVED for the
 * answer. It is always labelled "Retrieved source — support not verified"; the panel never says a
 * source supports a claim.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  type AvailableCitation,
  type Citation,
  type CitationNeighbor,
  MAX_CITATION_NEIGHBORS,
  getCitation,
} from '../../api/citations'
import { BackendError } from '../../api/client'
import { friendlyMessage } from '../../utils/errors'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { SidePanel } from '../ui/SidePanel'
import { ErrorState, LoadingState } from '../ui/States'
import styles from './CitationPanel.module.css'

export interface CitationTarget {
  conversationId: string
  messageId: string
  sourceId: string
}

export const SUPPORT_NOT_VERIFIED = 'Retrieved source — support not verified'

type State =
  | { kind: 'loading' }
  | { kind: 'loaded'; citation: Citation; withNeighbors: boolean }
  | { kind: 'error'; message: string; notFound: boolean }

function isNotFound(error: unknown): boolean {
  return error instanceof BackendError && (error.statusCode === 404 || error.statusCode === 403)
}

function Neighbors({ label, chunks }: { label: string; chunks: CitationNeighbor[] }) {
  if (chunks.length === 0) return null
  return (
    <section aria-label={label} className={styles.neighbors}>
      {chunks.map((chunk) => (
        <p key={chunk.chunk_id} className={styles.neighbor}>
          {chunk.text}
        </p>
      ))}
    </section>
  )
}

function Available({ citation }: { citation: AvailableCitation }) {
  const location = [
    citation.page !== null ? `Page ${citation.page}` : null,
    citation.section ? `Section: ${citation.section}` : null,
    `Passage ${citation.chunk_index + 1}`,
  ].filter(Boolean)
  return (
    <>
      <dl className={styles.meta}>
        <dt>Document</dt>
        <dd>
          <Link to={`/documents/${encodeURIComponent(citation.document_id)}?chunk=${citation.chunk_index}`}>
            {citation.filename}
          </Link>
        </dd>
        <dt>Location</dt>
        <dd>{location.join(' · ')}</dd>
        <dt>Cited in the answer</dt>
        <dd>{citation.cited ? 'Yes' : 'No — retrieved but not cited'}</dd>
      </dl>
      {citation.neighbors && <Neighbors label="Text before the passage" chunks={citation.neighbors.before} />}
      <figure className={styles.passage}>
        <figcaption className={styles.passageLabel}>Passage given to the model</figcaption>
        <blockquote className={styles.quote}>{citation.passage.text || '(empty passage)'}</blockquote>
        {citation.passage.truncated && (
          <p className={styles.note}>
            Only the start of this passage reached the model: the rest did not fit its context.
          </p>
        )}
      </figure>
      {citation.neighbors && <Neighbors label="Text after the passage" chunks={citation.neighbors.after} />}
    </>
  )
}

export function CitationPanel({ target, onClose }: { target: CitationTarget | null; onClose: () => void }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [neighbors, setNeighbors] = useState(0)
  const [attempt, setAttempt] = useState(0)

  // A new source starts without its surroundings.
  const [shownFor, setShownFor] = useState<CitationTarget | null>(target)
  if (target !== shownFor) {
    setShownFor(target)
    setNeighbors(0)
    setState({ kind: 'loading' })
  }

  useEffect(() => {
    if (!target) return
    const abort = new AbortController()
    getCitation({ ...target, neighbors }, abort.signal)
      .then((citation) => setState({ kind: 'loaded', citation, withNeighbors: neighbors > 0 }))
      .catch((error: unknown) => {
        if ((error as { name?: string }).name === 'AbortError') return
        setState({ kind: 'error', message: friendlyMessage(error), notFound: isNotFound(error) })
      })
    return () => abort.abort()
  }, [target, neighbors, attempt])

  const citation = state.kind === 'loaded' ? state.citation : null

  return (
    <SidePanel
      open={target !== null}
      title={target ? `Source ${target.sourceId}` : 'Source'}
      onClose={onClose}
      footer={
        citation?.status === 'available' ? (
          <Button
            size="sm"
            onClick={() => setNeighbors(neighbors > 0 ? 0 : MAX_CITATION_NEIGHBORS)}
            aria-pressed={neighbors > 0}
          >
            {neighbors > 0 ? 'Hide surrounding text' : 'Show surrounding text'}
          </Button>
        ) : undefined
      }
    >
      <p className={styles.support}>
        <Badge tone="warning">{SUPPORT_NOT_VERIFIED}</Badge>
      </p>
      <p className={styles.explain}>
        This passage was retrieved and given to the model for this answer. That alone does not show
        that it supports what the answer says.
      </p>
      {state.kind === 'loading' && <LoadingState label="Loading the source…" />}
      {state.kind === 'error' &&
        (state.notFound ? (
          <ErrorState title="This source could not be found" description="It may belong to a conversation you can no longer open." />
        ) : (
          <ErrorState title="The source could not be loaded" description={state.message} onRetry={() => {
              setState({ kind: 'loading' })
              setAttempt((n) => n + 1)
            }}
          />
        ))}
      {citation?.status === 'unavailable' && (
        <div className={styles.unavailable}>
          <p className={styles.unavailableTitle}>This source is no longer available</p>
          <p>
            It may have been deleted or made private, or you may no longer have access to it. Its
            contents are not shown.
          </p>
        </div>
      )}
      {citation?.status === 'available' && <Available citation={citation} />}
    </SidePanel>
  )
}
