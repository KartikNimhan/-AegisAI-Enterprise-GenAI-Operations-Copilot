export type StatusTone = 'healthy' | 'degraded' | 'unavailable' | 'unknown'

/** Maps a backend check ("ok" / "unavailable", or a boolean) to a badge tone; anything else is
 * unknown, never healthy. */
export function toneFromCheck(ok: string | boolean): StatusTone {
  if (typeof ok === 'boolean') return ok ? 'healthy' : 'unavailable'
  if (ok === 'ok') return 'healthy'
  if (ok === 'unavailable') return 'unavailable'
  return 'unknown'
}
