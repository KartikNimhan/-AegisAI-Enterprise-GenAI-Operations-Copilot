import { useState } from 'react'
import {
  getDocumentChunks,
  getEmbeddingStatus,
  type DocumentChunk,
  type DocumentRecord,
  type EmbeddingStatus,
} from '../../api/documents'
import { friendlyMessage } from '../../utils/errors'
import { formatDate } from '../../utils/format'
import styles from './DocumentDetails.module.css'

/** Metadata is shown from the list payload; chunks and embedding status are
 * fetched only when the user asks (mirrors the Streamlit Details expander). */
export function DocumentDetails({ doc }: { doc: DocumentRecord }) {
  const [chunks, setChunks] = useState<DocumentChunk[] | null>(null)
  const [chunkTotal, setChunkTotal] = useState(0)
  const [embedding, setEmbedding] = useState<EmbeddingStatus | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  async function loadChunks() {
    setError(null)
    try {
      const result = await getDocumentChunks(doc.id)
      setChunks(result.items)
      setChunkTotal(result.total)
    } catch (err) {
      setError(friendlyMessage(err))
    }
  }

  async function loadEmbedding() {
    setError(null)
    try {
      setEmbedding(await getEmbeddingStatus(doc.id))
    } catch (err) {
      setError(friendlyMessage(err))
    }
  }

  return (
    <div className={styles.details}>
      <dl className={styles.meta}>
        <dt>Document ID</dt>
        <dd>
          <code>{doc.id}</code>
        </dd>
        <dt>Content type</dt>
        <dd>{doc.content_type}</dd>
        <dt>Pages</dt>
        <dd>{doc.page_count ?? 'n/a'}</dd>
        <dt>Characters</dt>
        <dd>{doc.character_count ?? 'n/a'}</dd>
        <dt>Updated</dt>
        <dd>{formatDate(doc.updated_at)}</dd>
        <dt>Processed</dt>
        <dd>{doc.processed_at ? formatDate(doc.processed_at) : 'not processed'}</dd>
      </dl>

      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}

      <div className={styles.buttons}>
        <button type="button" onClick={loadChunks} disabled={doc.status !== 'processed'}>
          View chunks
        </button>
        <button type="button" onClick={loadEmbedding}>
          Embedding status
        </button>
      </div>

      {embedding === null && <p>No embeddings have been generated for this document.</p>}
      {embedding && (
        <p>
          Embeddings: {embedding.status} — {embedding.embedded_chunks} of {embedding.total_chunks}{' '}
          chunks ({embedding.provider} / {embedding.model}, {embedding.dimension} dimensions)
        </p>
      )}

      {chunks && (
        <div>
          <p>
            Showing {chunks.length} of {chunkTotal} chunks.
          </p>
          <ol className={styles.chunks}>
            {chunks.map((chunk) => (
              <li key={chunk.id} value={chunk.chunk_index + 1}>
                <span className={styles.chunkMeta}>{chunk.character_count} characters</span>
                <pre>{chunk.content}</pre>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}
