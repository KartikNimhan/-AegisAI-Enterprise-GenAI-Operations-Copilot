/** Wraps `GET /api/v1/auth/me` (app.api.v1.auth.MeResponse): the signed-in caller's own account. */

import { requestJson } from './client'

export interface Me {
  user_id: string
  organization_id: string
  email: string
  role: string
}

export async function getMe(signal?: AbortSignal): Promise<Me> {
  const me = await requestJson<Me>('/api/v1/auth/me', { signal })
  if (!me) throw new Error('The backend returned an empty response.')
  return me
}
