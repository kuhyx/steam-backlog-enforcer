// The app's cached server reads (see lib/query.ts), one per endpoint.

import { fetchBudget, fetchDataset } from '../api'
import { family, invalidateAll, Query } from '../lib/query'
import { api } from './client'
import type { Job } from './jobContract'

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])
export const isActive = (j: Job): boolean => !TERMINAL.has(j.state)

export const q = {
  status: new Query(api.status, { intervalMs: 15_000 }),
  stats: new Query(api.stats),
  installed: new Query(api.installed),
  library: new Query(api.library, { staleMs: 60_000 }),
  commands: new Query(api.commands, { intervalMs: 30_000 }),
  setup: new Query(api.setup),
  daemon: new Query(api.daemon, { intervalMs: 3_000 }),
  server: new Query(api.server, { intervalMs: 20_000 }),
  backups: new Query(api.backups),
  dataset: new Query(fetchDataset, { staleMs: 60_000 }),
  budget: new Query(() => fetchBudget(false), { intervalMs: 5_000 }),
  demoBudget: new Query(() => fetchBudget(true), { intervalMs: 5_000 }),
  jobs: new Query(api.jobs, { intervalMs: (data) => (data?.some(isActive) ? 2_000 : 15_000) }),
  job: family((id) =>
    new Query(() => api.job(id), { intervalMs: (data) => (data && !isActive(data) ? false : 2_000) }),
  ),
}

/** After a job ends, anything it may have changed is stale. */
export function refreshAfterJob(): void {
  invalidateAll()
}
