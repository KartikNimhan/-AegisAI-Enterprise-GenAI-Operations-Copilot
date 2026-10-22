/** Wraps `/api/v1/memories` (app.api.schemas.memories): the notes the agent keeps about the user. */

import { requestJson } from './client'

export type MemoryKind = 'fact' | 'preference'

export interface Memory {
  id: string
  kind: MemoryKind
  source: 'agent' | 'user'
  content: string
  created_at: string
  updated_at: string
  expires_at: string
}

export async function listMemories(signal?: AbortSignal): Promise<Memory[]> {
  return (await requestJson<Memory[]>('/api/v1/memories', { signal })) ?? []
}

export async function createMemory(content: string, kind: MemoryKind): Promise<Memory> {
  const memory = await requestJson<Memory>('/api/v1/memories', {
    method: 'POST',
    json: { content, kind },
  })
  if (!memory) throw new Error('The backend returned an empty response.')
  return memory
}

export async function updateMemory(id: string, content: string): Promise<Memory> {
  const memory = await requestJson<Memory>(`/api/v1/memories/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    json: { content },
  })
  if (!memory) throw new Error('The backend returned an empty response.')
  return memory
}

export async function deleteMemory(id: string): Promise<void> {
  await requestJson(`/api/v1/memories/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** Forgets everything. Returns how many notes were deleted. */
export async function clearMemories(): Promise<number> {
  const result = await requestJson<{ deleted: number }>('/api/v1/memories', { method: 'DELETE' })
  return result?.deleted ?? 0
}
