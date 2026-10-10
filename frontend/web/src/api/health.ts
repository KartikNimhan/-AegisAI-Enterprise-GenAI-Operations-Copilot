/** Wraps the liveness probe `GET /health` (app.api.schemas.common.HealthStatus). */

import { requestJson } from './client'

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const payload = await requestJson<{ status: string }>('/health', { signal })
    return payload?.status === 'ok'
  } catch {
    return false
  }
}
