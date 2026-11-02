/**
 * The production Content-Security-Policy, built the way docker-entrypoint.sh builds it.
 *
 * The policy TEMPLATE is read from docker-entrypoint.sh itself (the `CSP="…"` line), so this test
 * cannot drift from what the container sends. Only `${CONNECT_SRC}` and `${FRAME_SRC}` are filled
 * in, with the same rule the script uses: `'self'`, plus the API origin (connect-src) and the
 * identity provider's origin (connect-src and frame-src).
 */
import { readFileSync } from 'node:fs'

const ENTRYPOINT = new URL('../../docker-entrypoint.sh', import.meta.url)

/** `scheme://host[:port]` of an http(s) URL, or '' (the script's `origin_of`). */
export function originOf(url: string): string {
  const match = /^(https?:\/\/[^/]*)/.exec(url)
  return match ? match[1] : ''
}

export function policyTemplate(): string {
  const match = /^CSP="(.+)"$/m.exec(readFileSync(ENTRYPOINT, 'utf8'))
  if (!match) throw new Error('No CSP="…" line found in docker-entrypoint.sh')
  return match[1]
}

export function productionPolicy({ apiBaseUrl, oidcAuthority }: { apiBaseUrl: string; oidcAuthority: string }): string {
  let connect = "'self'"
  let frame = "'self'"
  const api = originOf(apiBaseUrl)
  const oidc = originOf(oidcAuthority)
  if (api) connect += ` ${api}`
  if (oidc) {
    connect += ` ${oidc}`
    frame += ` ${oidc}`
  }
  return policyTemplate().replace('${CONNECT_SRC}', connect).replace('${FRAME_SRC}', frame)
}
