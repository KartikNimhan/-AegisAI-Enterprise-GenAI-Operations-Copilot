import { useEffect, useState } from 'react'
import { checkHealth } from '../api/health'

const POLL_INTERVAL_MS = 15_000

/** Polls `GET /health` on an interval so the topbar can show a live
 * connection indicator — a real signal, not a static label. */
export function useBackendHealth(): boolean | null {
  const [isUp, setIsUp] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function poll() {
      const ok = await checkHealth(controller.signal)
      if (!cancelled) setIsUp(ok)
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(interval)
    }
  }, [])

  return isUp
}
