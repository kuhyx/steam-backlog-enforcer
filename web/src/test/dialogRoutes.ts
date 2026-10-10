// Routes every part of the runner dialog reads (catalog, game lookup, jobs).

import type { CommandSpec } from '../api/contract'
import { makeDataset, makeGame } from './factories'
import { makeInstalled, makeJob, makeStatus } from './fixtures'

/** Routes every screen of the dialog reads, plus whatever the test adds. */
export function routes(specs: CommandSpec[], extra: Record<string, unknown> = {}) {
  return {
    'GET /api/commands': specs,
    'GET /api/dataset': makeDataset([makeGame({ app_id: 7, name: 'Seven' })]),
    'GET /api/installed': { games: [makeInstalled({ app_id: 8, name: 'Eight' }), makeInstalled({ app_id: 9, name: 'Nine', assigned: true })] },
    'GET /api/status': makeStatus(),
    'GET /api/jobs': [],
    'GET /api/jobs/j1': makeJob({ id: 'j1' }),
    ...extra,
  }
}
