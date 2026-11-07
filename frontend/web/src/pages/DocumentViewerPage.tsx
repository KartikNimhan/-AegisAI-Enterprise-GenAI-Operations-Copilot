import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { BackendError } from '../api/client'
import {
  downloadDocumentFile,
  getDocument,
  getDocumentChunks,
  MAX_CHUNKS_PER_REQUEST,
  type DocumentChunk,
  type DocumentRecord,
} from '../api/documents'
import { Card } from '../components/Card'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { ErrorState, LoadingState } from '../components/ui/States'
import { friendlyMessage } from '../utils/errors'
import styles from './DocumentViewerPage.module.css'

type ViewState =
  | { state: 'loading' }
  | { state: 'missing' }
  | { state: 'error'; message: string }
  | { state: 'ready'; document: DocumentRecord; chunks: DocumentChunk[]; total: number }

/** `?chunk=<n>` from a citation, if it is a plain non-negative integer; anything else is ignored. */
function requestedChunk(raw: string | null): number | null {
  if (raw === null || !/^\d{1,6}$/.test(raw)) return null
  return Number(raw)
}

function pageOf(chunk: DocumentChunk): number | null {
  const value = chunk.metadata?.page_number
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null
}

/** The heading the passage falls under (M10.9; Markdown and DOCX documents ingested since then). */
function sectionOf(chunk: DocumentChunk): string | null {
  const value = chunk.metadata?.section
  return typeof value === 'string' && value.trim() ? value : null
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * The document viewer (M10.6): a document's details, its text as stored for search (grouped by
 * page when the page is known), and a download of the original file.
 *
 * - Everything comes from the scoped document endpoints, so a document the user cannot read (or
 *   that was deleted) shows one "not available" message, with nothing about it.
 * - `?chunk=<n>` (from a citation) loads up to that passage, highlights it and moves focus to it.
 * - The original is only ever downloaded, never opened inside the application.
 */
export function DocumentViewerPage() {
  const { documentId = '' } = useParams()
  const [params] = useSearchParams()
  const target = requestedChunk(params.get('chunk'))
  const [attempt, setAttempt] = useState(0)
  // The result is kept with the request it answers; a newer request reads as loading until its own
  // result arrives (no synchronous reset inside the effect).
  const requestKey = `${documentId}|${target ?? ''}|${attempt}`
  const [result, setResult] = useState<{ key: string; view: ViewState } | null>(null)
  const view: ViewState = result?.key === requestKey ? result.view : { state: 'loading' }
  const setView = (next: ViewState) => setResult({ key: requestKey, view: next })
  const [loadingMore, setLoadingMore] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const targetRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const document = await getDocument(documentId, controller.signal)
        const chunks: DocumentChunk[] = []
        let total = 0
        // Load the first page, then more only as far as the requested passage, and never past the
        // total the backend reports: a `?chunk=` beyond the document's end (a stale or edited link)
        // loads the first page only, instead of every page of the document (M10 review L9).
        do {
          const page = await getDocumentChunks(documentId, MAX_CHUNKS_PER_REQUEST, chunks.length)
          chunks.push(...page.items)
          total = page.total
          if (page.items.length === 0) break
        } while (target !== null && target < total && target >= chunks.length && chunks.length < total)
        if (!controller.signal.aborted) setResult({ key: requestKey, view: { state: 'ready', document, chunks, total } })
      } catch (error) {
        if (controller.signal.aborted) return
        const status = error instanceof BackendError ? error.statusCode : undefined
        setResult({
          key: requestKey,
          view: status === 404 || status === 403 ? { state: 'missing' } : { state: 'error', message: friendlyMessage(error) },
        })
      }
    }
    void load()
    return () => controller.abort()
  }, [documentId, target, requestKey])

  const ready = view.state === 'ready'
  useEffect(() => {
    if (!ready || !targetRef.current) return
    targetRef.current.scrollIntoView?.({ block: 'center' })
    targetRef.current.focus({ preventScroll: true })
  }, [ready])

  async function loadMore() {
    if (view.state !== 'ready') return
    setLoadingMore(true)
    try {
      const page = await getDocumentChunks(documentId, MAX_CHUNKS_PER_REQUEST, view.chunks.length)
      setView({ ...view, chunks: [...view.chunks, ...page.items], total: page.total })
    } catch (error) {
      setView({ state: 'error', message: friendlyMessage(error) })
    } finally {
      setLoadingMore(false)
    }
  }

  async function download(document: DocumentRecord) {
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadDocumentFile(document.id, document.filename)
    } catch (error) {
      const status = error instanceof BackendError ? error.statusCode : undefined
      setDownloadError(
        status === 404 || status === 403
          ? 'The original file is not available.'
          : `The original file could not be downloaded. ${friendlyMessage(error)}`,
      )
    } finally {
      setDownloading(false)
    }
  }

  const back = (
    <Link to="/documents" className={styles.back}>
      Back to documents
    </Link>
  )

  if (view.state === 'loading') {
    return (
      <div className={styles.page}>
        {back}
        <LoadingState label="Loading the document…" />
      </div>
    )
  }

  if (view.state === 'missing') {
    return (
      <div className={styles.page}>
        {back}
        <Card>
          <h2 className={styles.heading}>Document not available</h2>
          <p className={styles.muted}>
            It may have been deleted, or you may no longer have access to it.
          </p>
        </Card>
      </div>
    )
  }

  if (view.state === 'error') {
    return (
      <div className={styles.page}>
        {back}
        <ErrorState title="Could not load the document" description={view.message} onRetry={() => setAttempt((n) => n + 1)} />
      </div>
    )
  }

  const { document, chunks, total } = view
  const groups: { page: number | null; chunks: DocumentChunk[] }[] = []
  for (const chunk of chunks) {
    const page = pageOf(chunk)
    const last = groups.at(-1)
    if (last && last.page === page) last.chunks.push(chunk)
    else groups.push({ page, chunks: [chunk] })
  }

  return (
    <div className={styles.page}>
      {back}
      <Card className={styles.summary}>
        <div className={styles.titleRow}>
          <h2 className={styles.filename}>{document.filename}</h2>
          <Button variant="secondary" size="sm" busy={downloading} onClick={() => void download(document)}>
            Download original
          </Button>
        </div>
        <dl className={styles.facts}>
          <div>
            <dt>Type</dt>
            <dd>{document.document_type.toUpperCase()}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <Badge tone={document.status === 'processed' ? 'success' : document.status === 'failed' ? 'danger' : 'info'}>
                {document.status}
              </Badge>
            </dd>
          </div>
          {document.page_count !== null && (
            <div>
              <dt>Pages</dt>
              <dd>{document.page_count}</dd>
            </div>
          )}
          <div>
            <dt>Size</dt>
            <dd>{formatSize(document.file_size)}</dd>
          </div>
          <div>
            <dt>Passages</dt>
            <dd>{total}</dd>
          </div>
        </dl>
        {downloadError && (
          <p className={styles.error} role="alert">
            {downloadError}
          </p>
        )}
      </Card>

      <p className={styles.muted}>
        This is the text extracted for search, as the copilot sees it. Layout, images and formatting
        of the original are not shown; download the original to see them.
      </p>

      {target !== null && !chunks.some((chunk) => chunk.chunk_index === target) && (
        <p className={styles.notice} role="alert">
          The passage you followed is no longer part of this document.
        </p>
      )}

      {chunks.length === 0 ? (
        <Card>
          <p className={styles.muted}>No extracted text is stored for this document.</p>
        </Card>
      ) : (
        groups.map((group, index) => (
          <section key={`${group.page ?? 'none'}-${index}`} className={styles.group} aria-label={group.page ? `Page ${group.page}` : 'Text'}>
            {group.page !== null && <h3 className={styles.pageHeading}>Page {group.page}</h3>}
            {group.chunks.map((chunk) => {
              const isTarget = chunk.chunk_index === target
              return (
                <article
                  key={chunk.id}
                  id={`chunk-${chunk.chunk_index}`}
                  ref={isTarget ? targetRef : undefined}
                  tabIndex={isTarget ? -1 : undefined}
                  className={`${styles.passage} ${isTarget ? styles.target : ''}`}
                  aria-current={isTarget ? 'location' : undefined}
                  aria-label={`Passage ${chunk.chunk_index + 1}${isTarget ? ', the cited passage' : ''}`}
                >
                  <p className={styles.passageLabel}>
                    Passage {chunk.chunk_index + 1}
                    {sectionOf(chunk) && <span className={styles.section}>· {sectionOf(chunk)}</span>}
                    {isTarget && <Badge tone="citation">Cited passage</Badge>}
                  </p>
                  <p className={styles.text}>{chunk.content}</p>
                </article>
              )
            })}
          </section>
        ))
      )}

      {chunks.length < total && (
        <Button variant="secondary" busy={loadingMore} onClick={() => void loadMore()}>
          Load more passages ({chunks.length} of {total})
        </Button>
      )}
    </div>
  )
}
