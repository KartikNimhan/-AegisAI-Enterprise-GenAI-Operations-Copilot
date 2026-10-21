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

const STATUS_MESSAGES: Record<number, string> = {
  401: 'You are not signed in, or your session has expired. Please sign in again.',
  403: 'You do not have permission to do that.',
  503: 'The service is temporarily unavailable. Please try again shortly.',
}

export function friendlyMessage(error: unknown): string {
  if (error instanceof BackendError) {
    return (
      FRONTEND_MESSAGES[error.code] ??
      (error.statusCode !== undefined ? STATUS_MESSAGES[error.statusCode] : undefined) ??
      error.message
    )
  }
  if (error instanceof Error) return error.message
  return 'Something went wrong.'
}
