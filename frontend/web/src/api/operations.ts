/** Wraps Milestone 9's `/api/v1/operations/summary` (app.api.schemas.operations). */

import { requestJson } from './client'

export interface OperationsSummary {
  total_documents: number
  documents_by_status: Record<string, number>
}

export async function getOperationsSummary(): Promise<OperationsSummary> {
  const payload = await requestJson<OperationsSummary>('/api/v1/operations/summary')
  return payload ?? { total_documents: 0, documents_by_status: {} }
}
