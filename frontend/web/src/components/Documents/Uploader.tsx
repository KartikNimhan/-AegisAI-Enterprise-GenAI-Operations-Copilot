import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { Icon } from '../Icon'
import { uploadDocumentWithProgress } from '../../api/documents'
import { friendlyMessage } from '../../utils/errors'
import styles from './Uploader.module.css'

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown']

export function Uploader({ onUploaded }: { onUploaded: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleFile(file: File) {
    setError(null)
    setProgress(0)
    try {
      await uploadDocumentWithProgress(file, setProgress)
      onUploaded()
    } catch (err) {
      setError(friendlyMessage(err))
    } finally {
      setProgress(null)
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragOver(false)
    const file = event.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <div className={styles.container}>
      <div
        className={`${styles.dropzone} ${dragOver ? styles.dragOver : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
      >
        <Icon name="upload" size={24} />
        <p className={styles.text}>
          <strong>Click to upload</strong> or drag and drop
        </p>
        <p className={styles.hint}>PDF, DOCX, TXT, or Markdown</p>
        <input
          ref={inputRef}
          type="file"
          accept={ALLOWED_EXTENSIONS.join(',')}
          className={styles.hiddenInput}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFile(file)
            e.target.value = ''
          }}
        />
      </div>

      {progress !== null && (
        <div className={styles.progressTrack}>
          <div className={styles.progressFill} style={{ width: `${progress}%` }} />
          <span className={styles.progressLabel}>Uploading… {progress}%</span>
        </div>
      )}

      {error && (
        <p className={styles.error}>
          <Icon name="alert" size={14} /> {error}
        </p>
      )}
    </div>
  )
}
