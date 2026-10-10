/**
 * Maps a `BackendError` into a user-facing message — never a raw
 * exception string. A structured backend error already carries a safe
 * message (see app.core.exceptions); a connectivity-level failure
 * (assigned client-side, never by the backend) gets one of these.
 * Mirrors frontend/streamlit/components/errors.py.
 */

import { BackendError } from '../api/client'

const FRONTEND_MESSAGES: Record<string, string> = {
  timeout: 'The backend did not respond in time. Please try again.',
  network_error: 'Unable to reach the backend. Check that it is running.',
  malformed_response: 'The backend returned an unexpected response.',
}

export function friendlyMessage(error: unknown): string {
  if (error instanceof BackendError) {
    return FRONTEND_MESSAGES[error.code] ?? error.message
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
