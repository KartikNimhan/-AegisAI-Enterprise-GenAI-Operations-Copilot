/** Pages the preview may open first (`?route=/documents`). Anything else opens the Copilot. */
export const PREVIEW_ROUTES = ['/', '/conversations', '/documents', '/memory', '/operations', '/system']

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]']

/**
 * Whether the preview may run at all. Both must hold:
 * - `dev` is Vite's `import.meta.env.DEV`, which is statically false in a production build, so
 *   the preview cannot run in one even if its page were somehow served;
 * - the page is open on this machine, not served to anyone else.
 */
export function previewAllowed(dev: boolean, hostname: string): boolean {
  return dev === true && LOCAL_HOSTS.includes(hostname)
}

export function previewRoute(search: string): string {
  const requested = new URLSearchParams(search).get('route')
  return requested !== null && PREVIEW_ROUTES.includes(requested) ? requested : '/'
}
