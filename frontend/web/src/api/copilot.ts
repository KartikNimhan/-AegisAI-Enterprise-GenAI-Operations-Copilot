/** Wraps `POST /api/v1/multi-agent/run` (app.api.schemas.multi_agent). */

import { requestJson } from './client'

export interface AgentStatus {
  agent_name: string
  capability: string
  status: string
  error: string | null
  duration_ms: number
  retry_count: number
}

export interface MultiAgentRunResult {
  workflow_id: string
  correlation_id: string
  status: string
  answer: string
  agents_used: AgentStatus[]
  sources: Record<string, unknown>[]
  token_usage: Record<string, unknown>
  duration_ms: number
}

export async function runMultiAgentWorkflow(
  message: string,
  signal?: AbortSignal,
): Promise<MultiAgentRunResult> {
  const result = await requestJson<MultiAgentRunResult>('/api/v1/multi-agent/run', {
    method: 'POST',
    json: { message },
    signal,
  })
  if (!result) {
    throw new Error('The backend returned an empty response.')
  }
  return result
}
