/** Wraps `/api/v1/conversations` (app.api.schemas.conversations). */

import { requestJson } from './client'

export interface ConversationSummary {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

/** A saved citation as listed with a reopened conversation (M10.4). Source fields are null
 * unless `status` is "available": the backend never describes a source the caller can no longer
 * read. There is no passage text here; the citation endpoint returns it. */
export interface MessageCitationSummary {
  source_id: string
  status: 'available' | 'unavailable'
  cited: boolean
  /** Null unless `status` is "available" (an unavailable source reveals nothing). */
  passage_truncated: boolean | null
  support: 'not_verified'
  document_id: string | null
  chunk_id: string | null
  filename: string | null
  chunk_index: number | null
  page: number | null
  section: string | null
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  model: string | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  created_at: string
  /** Empty for user messages, answers without sources and messages saved before M10.4. */
  citations?: MessageCitationSummary[]
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[]
}

export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  return (await requestJson<ConversationSummary[]>('/api/v1/conversations', { signal })) ?? []
}

export async function getConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail> {
  const detail = await requestJson<ConversationDetail>(
    `/api/v1/conversations/${encodeURIComponent(id)}`,
    { signal },
  )
  if (!detail) throw new Error('The backend returned an empty response.')
  return detail
}

export async function deleteConversation(id: string): Promise<void> {
  await requestJson(`/api/v1/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
