import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { q } from '../api/queries'

/**
 * Restart the web server. Its token changes with the process, so once the
 * new instance answers with a later `started_at` the page reloads to pick
 * the new token up from index.html.
 */
export function useServerRestart() {
  const server = useQuery(q.server)
  const [waitingFor, setWaitingFor] = useState<string | null>(null)
  const restart = useMutation({
    mutationFn: api.restartServer,
    onSuccess: () => setWaitingFor(server.data?.started_at ?? ''),
  })
  const startedAt = server.data?.started_at
  useEffect(() => {
    if (waitingFor !== null && startedAt && startedAt !== waitingFor) window.location.reload()
  }, [waitingFor, startedAt])
  return { restart, restarting: waitingFor !== null }
}
