import { useEffect, useState } from 'react'
import { fetchBudget } from './api'
import type { BudgetSnapshot } from './types'

export interface BudgetPollState {
  data: BudgetSnapshot | null
  error: string | null
}

/** Poll interval. The daemon ticks every ~3s, so this is about as fresh as the data gets. */
export const POLL_MS = 5000

/**
 * Poll `/api/budget` for as long as the panel is mounted.
 *
 * Visibility is deliberately not consulted. A `document.hidden` guard used to
 * skip the request, but it also swallowed the very first load, so a panel that
 * mounted in a background tab sat on "Reading budget state…" with no data and
 * no error. Every tab driven by browser automation is hidden, which made the
 * panel unreadable that way. Switching tabs already unmounts the hook, so the
 * only cost of dropping the guard is one request per interval in a background
 * tab left open.
 */
export function useBudgetPoll(demo: boolean, intervalMs: number = POLL_MS): BudgetPollState {
  const [data, setData] = useState<BudgetSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetchBudget(demo)
        .then((snapshot) => {
          // A response can arrive after unmount; committing it would warn and,
          // worse, resurrect stale data on the next mount.
          if (cancelled) return
          setData(snapshot)
          setError(null)
        })
        .catch((e: unknown) => {
          if (cancelled) return
          setError(e instanceof Error ? e.message : String(e))
        })
    }

    load()
    const id = setInterval(load, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [demo, intervalMs])

  return { data, error }
}
