/**
 * Resolves the backend API base URL.
 *
 * This code runs in the user's browser, never inside a Docker container —
 * so it must always use a host-reachable URL (the backend's
 * Docker-published port, e.g. http://localhost:8000), never the internal
 * Docker Compose service name (http://backend:8000), which only resolves
 * *between* containers on the Compose network, not from the host browser.
 *
 * Resolution order:
 * 1. `window.__AEGIS_CONFIG__.apiBaseUrl` — injected at container start by
 *    docker-entrypoint.sh from the `API_BASE_URL` environment variable, so
 *    the same built image can point at a different backend without a
 *    rebuild (see frontend/web/Dockerfile).
 * 2. `VITE_API_BASE_URL` — baked in at build time for `npm run build`/
 *    `vite preview` without the runtime script.
 * 3. `http://localhost:8000` — the default for `npm run dev` and for
 *    docker-compose.yml's default backend port mapping.
 */

declare global {
  interface Window {
    __AEGIS_CONFIG__?: {
      apiBaseUrl?: string
    }
  }
}

const DEFAULT_API_BASE_URL = 'http://localhost:8000'

export function getApiBaseUrl(): string {
  const runtimeUrl = window.__AEGIS_CONFIG__?.apiBaseUrl
  if (runtimeUrl) return runtimeUrl

  const buildTimeUrl = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (buildTimeUrl) return buildTimeUrl

  return DEFAULT_API_BASE_URL
}
