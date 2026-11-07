/** Wraps Milestone 3's `/api/v1/documents` endpoints (app.api.schemas.documents). */

import { BackendError, parseErrorResponse, requestJson } from './client'
import { authHeaders, notifyUnauthorized } from '../auth/token'
import { getApiBaseUrl } from '../config'

export interface DocumentRecord {
  id: string
  filename: string
  content_type: string
  document_type: string
  file_size: number
  status: string
  error_message: string | null
  page_count: number | null
  character_count: number | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
  processed_at: string | null
}

export interface DocumentUploadRecord extends DocumentRecord {
  is_duplicate: boolean
}

export interface EmbeddingStatus {
  document_id: string
  provider: string
  model: string
  model_version: string
  dimension: number
  total_chunks: number
  embedded_chunks: number
  status: string
}

interface ListResponse<T> {
  items: T[]
  total: number
}

export async function listDocuments(
  limit = 100,
  offset = 0,
): Promise<{ items: DocumentRecord[]; total: number }> {
  const payload = await requestJson<ListResponse<DocumentRecord>>('/api/v1/documents', {
    params: { limit, offset },
  })
  return { items: payload?.items ?? [], total: payload?.total ?? 0 }
}

export async function uploadDocument(file: File): Promise<DocumentUploadRecord> {
  const formData = new FormData()
  formData.append('file', file)
  const payload = await requestJson<DocumentUploadRecord>('/api/v1/documents', {
    method: 'POST',
    formData,
    okStatusCodes: [200, 201],
  })
  if (!payload) throw new Error('The backend returned an empty response.')
  return payload
}

/** Uses XMLHttpRequest (not fetch) only because fetch has no portable
 * upload-progress event — everything else in this module stays on the
 * shared fetch-based `requestJson` client. */
export function uploadDocumentWithProgress(
  file: File,
  onProgress: (percent: number) => void,
): Promise<DocumentUploadRecord> {
  return new Promise((resolve, reject) => {
    const formData = new FormData()
    formData.append('file', file)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', new URL('/api/v1/documents', getApiBaseUrl()).toString())
    for (const [name, value] of Object.entries(authHeaders())) xhr.setRequestHeader(name, value)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }

    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new BackendError('The backend returned an unexpected response.', { code: 'malformed_response' }))
        }
      } else {
        if (xhr.status === 401) notifyUnauthorized()
        try {
          const payload = JSON.parse(xhr.responseText)
          reject(
            new BackendError(payload?.error?.message ?? `The backend returned HTTP ${xhr.status}`, {
              code: payload?.error?.code ?? 'http_error',
              statusCode: xhr.status,
            }),
          )
        } catch {
          reject(new BackendError(`The backend returned HTTP ${xhr.status}`, { code: 'http_error', statusCode: xhr.status }))
        }
      }
    }

    xhr.onerror = () => {
      reject(new BackendError('Could not reach the backend. Check that it is running.', { code: 'network_error' }))
    }
    xhr.ontimeout = () => {
      reject(new BackendError('The backend did not respond in time. Please try again.', { code: 'timeout' }))
    }
    xhr.timeout = 60_000

    xhr.send(formData)
  })
}

export async function deleteDocument(documentId: string): Promise<void> {
  await requestJson(`/api/v1/documents/${documentId}`, {
    method: 'DELETE',
    okStatusCodes: [204],
  })
}

export async function triggerEmbeddings(documentId: string): Promise<void> {
  await requestJson(`/api/v1/documents/${documentId}/embeddings`, { method: 'POST' })
}

export interface DocumentChunk {
  id: string
  chunk_index: number
  content: string
  character_count: number
  token_count: number | null
  metadata: Record<string, unknown> | null
  created_at: string
}

/** Chunks are fetched on demand (details view), never with the list. */
export async function getDocumentChunks(
  documentId: string,
  limit = 10,
  offset = 0,
): Promise<{ items: DocumentChunk[]; total: number }> {
  const payload = await requestJson<ListResponse<DocumentChunk>>(
    `/api/v1/documents/${documentId}/chunks`,
    { params: { limit, offset } },
  )
  return { items: payload?.items ?? [], total: payload?.total ?? 0 }
}

export async function getEmbeddingStatus(documentId: string): Promise<EmbeddingStatus | null> {
  return requestJson<EmbeddingStatus>(`/api/v1/documents/${documentId}/embeddings`)
}

/** One document's details; `null` never means "missing": a missing or unreadable one is a 404. */
export async function getDocument(documentId: string, signal?: AbortSignal): Promise<DocumentRecord> {
  const document = await requestJson<DocumentRecord>(`/api/v1/documents/${encodeURIComponent(documentId)}`, { signal })
  if (!document) throw new Error('The backend returned an empty response.')
  return document
}

/** The most chunks the backend returns per request (`limit` is capped at 200). */
export const MAX_CHUNKS_PER_REQUEST = 200

/**
 * Downloads the original uploaded file (M10.6, `GET /documents/{id}/file`) and hands it to the
 * browser as a download. The file is never opened inside the application: it is untrusted content,
 * and the backend sends it as an attachment with a sandboxing policy. `filename` is the name the
 * caller already knows from the document's details.
 */
export async function downloadDocumentFile(documentId: string, filename: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${getApiBaseUrl()}/api/v1/documents/${encodeURIComponent(documentId)}/file`, {
      headers: authHeaders(),
    })
  } catch {
    throw new BackendError('Could not reach the backend. Check that it is running.', { code: 'network_error' })
  }
  if (!response.ok) {
    if (response.status === 401) notifyUnauthorized()
    throw await parseErrorResponse(response)
  }
  const url = URL.createObjectURL(await response.blob())
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.rel = 'noopener'
    document.body.append(link)
    link.click()
    link.remove()
  } finally {
    // Give the browser a moment to start the download before the object URL is released.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
