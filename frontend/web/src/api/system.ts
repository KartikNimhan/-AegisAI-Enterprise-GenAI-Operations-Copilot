/**
 * Wraps Milestone 9's `/api/v1/system/status` (app.api.schemas.system).
 * `database`/`redis` are live connectivity checks; `llm_configured`/
 * `trusted_a2a_agents`/`mcp_server` are configuration facts, not live
 * probes — render them distinctly, per the backend schema's own docstring.
 */

import { requestJson } from './client'

export interface SystemStatus {
  database: string
  redis: string
  llm_configured: boolean
  trusted_a2a_agents: string[]
  mcp_server: string
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const payload = await requestJson<SystemStatus>('/api/v1/system/status')
  return (
    payload ?? {
      database: 'unknown',
      redis: 'unknown',
      llm_configured: false,
      trusted_a2a_agents: [],
      mcp_server: '',
    }
  )
}
