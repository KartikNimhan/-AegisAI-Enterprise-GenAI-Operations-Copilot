/**
 * Wraps `GET /api/v1/conversations/{id}/messages/{id}/citations/{source_id}` (M10.4 T6).
 *
 * The backend re-checks the caller's CURRENT access on every call. An "unavailable" answer carries
 * no file name, page, ids or text (deleted, made private, never readable and passage mismatch all
 * look the same), and `support` is always "not_verified": retrieval alone never proves a claim.
 */

import { requestJson } from './client'

export interface CitationNeighbor {
  chunk_id: string
  chunk_index: number
  page: number | null
  section: string | null
  text: string
}

export interface AvailableCitation {
  status: 'available'
  message_id: string
  source_id: string
  cited: boolean
  support: 'not_verified'
  document_id: string
  chunk_id: string
  filename: string
  chunk_index: number
  page: number | null
  section: string | null
  similarity: number
  passage: { text: string; characters: number; truncated: boolean }
  neighbors: { before: CitationNeighbor[]; after: CitationNeighbor[] } | null
}

export interface UnavailableCitation {
  status: 'unavailable'
  message_id: string
  source_id: string
  cited: boolean
  support: 'not_verified'
}

export type Citation = AvailableCitation | UnavailableCitation

/** At most two chunks on each side (M10.4 decision 6). */
export const MAX_CITATION_NEIGHBORS = 2

export async function getCitation(
  {
    conversationId,
    messageId,
    sourceId,
    neighbors = 0,
  }: { conversationId: string; messageId: string; sourceId: string; neighbors?: number },
  signal?: AbortSignal,
): Promise<Citation> {
  if (!/^S[1-9][0-9]{0,2}$/.test(sourceId)) throw new Error(`Not a source id: ${sourceId}`)
  const path =
    `/api/v1/conversations/${encodeURIComponent(conversationId)}` +
    `/messages/${encodeURIComponent(messageId)}/citations/${encodeURIComponent(sourceId)}`
  const citation = await requestJson<Citation>(path, {
    params: neighbors > 0 ? { neighbors: Math.min(neighbors, MAX_CITATION_NEIGHBORS) } : undefined,
    signal,
  })
  if (!citation) throw new Error('The backend returned an empty response.')
  return citation
}
