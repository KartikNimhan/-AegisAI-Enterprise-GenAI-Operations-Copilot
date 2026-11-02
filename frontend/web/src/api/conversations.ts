/** Wraps `/api/v1/conversations` (app.api.schemas.conversations). */

import { requestJson } from './client'

export interface ConversationSummary {
  id: string
  title: string | null
  created_at: string
  updated_at: string
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
