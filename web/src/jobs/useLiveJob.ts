import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { hub, type LiveJob } from './hub'

/** Follow a job's SSE stream for as long as the caller is mounted. */
export function useLiveJob(id: string | null): LiveJob | null {
  useEffect(() => (id ? hub.watch(id) : undefined), [id])
  const snapshot = useCallback(() => (id ? hub.get(id) : null), [id])
  return useSyncExternalStore(hub.subscribe, snapshot)
}
