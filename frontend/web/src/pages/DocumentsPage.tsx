import { useCallback, useEffect, useState } from 'react'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { StatusPill } from '../components/Documents/StatusPill'
import { Uploader } from '../components/Documents/Uploader'
import { deleteDocument, listDocuments, triggerEmbeddings, type DocumentRecord } from '../api/documents'
import { friendlyMessage } from '../utils/errors'
import { formatBytes, formatDate } from '../utils/format'
import styles from './DocumentsPage.module.css'

export function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const { items } = await listDocuments()
      setDocuments(items)
    } catch (err) {
      setError(friendlyMessage(err))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function handleDelete(id: string) {
    setBusyId(id)
    try {
      await deleteDocument(id)
      await refresh()
    } catch (err) {
      setError(friendlyMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function handleEmbed(id: string) {
    setBusyId(id)
    try {
      await triggerEmbeddings(id)
      await refresh()
    } catch (err) {
      setError(friendlyMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className={styles.page}>
      <Uploader onUploaded={refresh} />

      {error && (
        <p className={styles.error}>
          <Icon name="alert" size={14} /> {error}
        </p>
      )}

      <Card>
        {documents === null ? (
          <div className={styles.loading}>Loading documents…</div>
        ) : documents.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description="Upload a PDF, DOCX, TXT, or Markdown file above to get started."
          />
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Size</th>
                <th>Status</th>
                <th>Uploaded</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td className={styles.filename}>{doc.filename}</td>
                  <td>{doc.document_type}</td>
                  <td>{formatBytes(doc.file_size)}</td>
                  <td>
                    <StatusPill status={doc.status} />
                    {doc.status === 'failed' && doc.error_message && (
                      <div className={styles.errorMessage}>{doc.error_message}</div>
                    )}
                  </td>
                  <td>{formatDate(doc.created_at)}</td>
                  <td className={styles.actions}>
                    <button
                      type="button"
                      className={styles.actionButton}
                      disabled={busyId === doc.id || doc.status !== 'processed'}
                      onClick={() => handleEmbed(doc.id)}
                      title="Generate embeddings"
                    >
                      <Icon name="refresh" size={14} />
                    </button>
                    <button
                      type="button"
                      className={styles.actionButton}
                      disabled={busyId === doc.id}
                      onClick={() => handleDelete(doc.id)}
                      title="Delete document"
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
