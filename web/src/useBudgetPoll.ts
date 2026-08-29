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
 * Poll `/api/budget` while mounted, pausing whenever the tab is hidden.
 *
 * The hook is only mounted by the budget tab, so switching away stops the
 * requests entirely; the `document.hidden` check covers the other case, a tab
 * left open in the background for hours.
 */
export function useBudgetPoll(demo: boolean, intervalMs: number = POLL_MS): BudgetPollState {
  const [data, setData] = useState<BudgetSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = () => {
      if (document.hidden) return
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
