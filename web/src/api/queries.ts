// TanStack Query bindings. Polling queries set `refetchIntervalInBackground`
// because automation tabs (and a Chrome --app window behind another) report
// hidden, and a paused poll there shows frozen state.

import { queryOptions, QueryClient } from '@tanstack/react-query'
import { fetchBudget, fetchDataset } from '../api'
import { api } from './client'
import type { Job } from './jobContract'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true },
  },
})

const live = (ms: number) => ({ refetchInterval: ms, refetchIntervalInBackground: true })

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])
export const isActive = (j: Job) => !TERMINAL.has(j.state)

export const q = {
  status: queryOptions({ queryKey: ['status'], queryFn: api.status, ...live(15_000) }),
  stats: queryOptions({ queryKey: ['stats'], queryFn: api.stats }),
  installed: queryOptions({ queryKey: ['installed'], queryFn: api.installed }),
  library: queryOptions({ queryKey: ['library'], queryFn: api.library, staleTime: 60_000 }),
  commands: queryOptions({ queryKey: ['commands'], queryFn: api.commands, ...live(30_000) }),
  setup: queryOptions({ queryKey: ['setup'], queryFn: api.setup }),
  daemon: queryOptions({ queryKey: ['daemon'], queryFn: api.daemon, ...live(3_000) }),
  server: queryOptions({ queryKey: ['server'], queryFn: api.server, ...live(20_000) }),
  backups: queryOptions({ queryKey: ['backups'], queryFn: api.backups }),
  dataset: queryOptions({ queryKey: ['dataset'], queryFn: fetchDataset, staleTime: 60_000 }),
  budget: queryOptions({ queryKey: ['budget'], queryFn: () => fetchBudget(false), ...live(5_000) }),
  jobs: queryOptions({
    queryKey: ['jobs'],
    queryFn: api.jobs,
    refetchInterval: (query) => (query.state.data?.some(isActive) ? 2_000 : 15_000),
    refetchIntervalInBackground: true,
  }),
  job: (id: string) =>
    queryOptions({
      queryKey: ['jobs', id],
      queryFn: () => api.job(id),
      refetchInterval: (query) => (query.state.data && !isActive(query.state.data) ? false : 2_000),
      refetchIntervalInBackground: true,
    }),
}

/** After a job ends, anything it may have changed is stale. */
export function refreshAfterJob(): void {
  void queryClient.invalidateQueries()
}
