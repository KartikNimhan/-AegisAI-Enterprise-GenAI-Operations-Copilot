import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ConversationSummary } from '../api/conversations'
import type { OperationsSummary } from '../api/operations'
import {
  loadConversations,
  loadMemoryCount,
  loadOperationsSummary,
  loadSystemStatus,
  MalformedDataError,
} from '../api/overview'
import type { SystemStatus } from '../api/system'
import { isAdmin, useAccount } from '../auth/AccountContext'
import { Card } from '../components/Card'
import { Badge, type BadgeTone } from '../components/ui/Badge'
import { useBackendHealth } from '../hooks/useBackendHealth'
import styles from './OverviewPage.module.css'

/** A value that is still loading, was loaded, could not be loaded (`unavailable`), or came back
 * without a usable body (`malformed`: a 204, an empty 200 or the wrong shape). Neither of the last
 * two is ever shown as zero (M10 decision 11); a real zero is `ready` with the value 0. */
type Loadable<T> =
  | { state: 'loading' }
  | { state: 'ready'; value: T }
  | { state: 'unavailable' }
  | { state: 'malformed' }

const RECENT_LIMIT = 5

const STATUS_LABEL: Record<string, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  processed: 'Processed',
  failed: 'Failed',
}

function useLoad<T>(load: (() => Promise<T>) | null): Loadable<T> {
  const [result, setResult] = useState<Loadable<T>>({ state: 'loading' })
  // The loader is fixed for the life of the page, so the data is fetched once on mount.
  const [loader] = useState(() => load)
  useEffect(() => {
    if (!loader) return
    let active = true
    loader()
      .then((value) => active && setResult({ state: 'ready', value }))
      .catch((error) =>
        active && setResult({ state: error instanceof MalformedDataError ? 'malformed' : 'unavailable' }),
      )
    return () => {
      active = false
    }
  }, [loader])
  return result
}

/** Says why there is nothing to show; renders nothing while loading or once loaded. */
function NotLoaded({ state }: { state: Loadable<unknown>['state'] }) {
  if (state === 'unavailable') {
    return <p className={styles.unavailable}>Unavailable: the request to the backend failed.</p>
  }
  if (state === 'malformed') {
    return (
      <p className={styles.unavailable}>Unavailable: the backend answered without usable data.</p>
    )
  }
  return null
}

function Loading() {
  return <p className={styles.muted}>Loading…</p>
}

/**
 * The Overview (M10.2): a summary built only from data the backend really returns. Nothing is
 * estimated or invented, and data that could not be loaded says so instead of reading as zero.
 */
export function OverviewPage() {
  const admin = isAdmin(useAccount())
  const health = useBackendHealth()
  const documents = useLoad<OperationsSummary>(loadOperationsSummary)
  const conversations = useLoad<ConversationSummary[]>(loadConversations)
  const memories = useLoad<number>(loadMemoryCount)
  const system = useLoad<SystemStatus>(admin ? loadSystemStatus : null)

  return (
    <div className={styles.page}>
      <p className={styles.intro}>
        A summary of what the backend has stored for you. No usage, cost or quality metrics are shown,
        because none are recorded yet.
      </p>

      <div className={styles.grid}>
        <Card className={styles.card}>
          <h2 className={styles.heading}>Documents</h2>
          {documents.state === 'loading' && <Loading />}
          <NotLoaded state={documents.state} />
          {documents.state === 'ready' && (
            <>
              <p className={styles.figure}>
                <span className={styles.value}>{documents.value.total_documents}</span>
                <span className={styles.muted}>
                  {documents.value.total_documents === 1 ? 'document' : 'documents'}
                </span>
              </p>
              <dl className={styles.breakdown}>
                {Object.entries(documents.value.documents_by_status).map(([status, count]) => (
                  <div key={status} className={styles.row}>
                    <dt>{STATUS_LABEL[status] ?? status}</dt>
                    <dd>{count}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          <Link className={styles.more} to="/documents">
            Manage documents
          </Link>
        </Card>

        <Card className={styles.card}>
          <h2 className={styles.heading}>Recent conversations</h2>
          {conversations.state === 'loading' && <Loading />}
          <NotLoaded state={conversations.state} />
          {conversations.state === 'ready' &&
            (conversations.value.length === 0 ? (
              <p className={styles.muted}>No conversations yet.</p>
            ) : (
              <ul className={styles.list}>
                {conversations.value.slice(0, RECENT_LIMIT).map((conversation) => (
                  <li key={conversation.id}>
                    <Link to={`/?conversation=${encodeURIComponent(conversation.id)}`} className={styles.item}>
                      {conversation.title?.trim() || 'Untitled conversation'}
                    </Link>
                    <span className={styles.muted}>
                      {' '}
                      · <time dateTime={conversation.updated_at}>{formatDate(conversation.updated_at)}</time>
                    </span>
                  </li>
                ))}
              </ul>
            ))}
          <Link className={styles.more} to="/conversations">
            All conversations
          </Link>
        </Card>

        <Card className={styles.card}>
          <h2 className={styles.heading}>Memory</h2>
          {memories.state === 'loading' && <Loading />}
          <NotLoaded state={memories.state} />
          {memories.state === 'ready' && (
            <p className={styles.figure}>
              <span className={styles.value}>{memories.value}</span>
              <span className={styles.muted}>{memories.value === 1 ? 'saved note' : 'saved notes'}</span>
            </p>
          )}
          <Link className={styles.more} to="/memory">
            Review memory
          </Link>
        </Card>

        <Card className={styles.card}>
          <h2 className={styles.heading}>Service</h2>
          <dl className={styles.breakdown}>
            <div className={styles.row}>
              <dt>Backend</dt>
              <dd>
                {health === null ? (
                  <Badge>Checking</Badge>
                ) : health ? (
                  <Badge tone="success">Reachable</Badge>
                ) : (
                  <Badge tone="danger">Unreachable</Badge>
                )}
              </dd>
            </div>
            {admin && system.state === 'ready' && (
              <>
                <div className={styles.row}>
                  <dt>Database</dt>
                  <dd>
                    <Badge tone={toneFor(system.value.database)}>{system.value.database}</Badge>
                  </dd>
                </div>
                <div className={styles.row}>
                  <dt>Redis</dt>
                  <dd>
                    <Badge tone={toneFor(system.value.redis)}>{system.value.redis}</Badge>
                  </dd>
                </div>
              </>
            )}
          </dl>
          {admin && system.state === 'loading' && <Loading />}
          {admin && <NotLoaded state={system.state} />}
          {admin && (
            <Link className={styles.more} to="/system">
              System status
            </Link>
          )}
        </Card>
      </div>
    </div>
  )
}

/** The backend reports "ok" or "unavailable"; anything else is shown as unknown, not as healthy. */
function toneFor(value: string): BadgeTone {
  if (value === 'ok') return 'success'
  if (value === 'unavailable') return 'danger'
  return 'warning'
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? 'unknown date' : date.toLocaleDateString()
}
