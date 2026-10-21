/**
 * The bridge between the auth layer (React) and the API client (plain
 * functions). The client attaches whatever token is current and reports a 401;
 * it never knows about React or the identity provider.
 */

let accessToken: string | null = null
let unauthorizedHandler: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

/** Called by the API client when the backend answers 401 to a request. */
export function notifyUnauthorized(): void {
  unauthorizedHandler?.()
}

/** `Authorization` header for the current token, or nothing when signed out. */
export function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}
