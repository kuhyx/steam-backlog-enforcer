import { QueryObserver } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeBudget, makeDataset } from '../test/factories'
import { makeJob } from '../test/fixtures'
import { stubApi } from '../test/harness'
import { isActive, q, queryClient, refreshAfterJob } from './queries'

type Interval = number | false | undefined | ((query: never) => number | false | undefined)
const intervalOf = (o: { refetchInterval?: unknown }, data: unknown): unknown => {
  const f = o.refetchInterval as Interval
  return typeof f === 'function' ? (f as (x: unknown) => unknown)({ state: { data } }) : f
}

describe('queries', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('isActive is false only for terminal states', () => {
    expect(isActive(makeJob({ state: 'running' }))).toBe(true)
    expect(isActive(makeJob({ state: 'waiting_input' }))).toBe(true)
    expect(isActive(makeJob({ state: 'succeeded' }))).toBe(false)
  })

  it('polls jobs fast while one is active, slowly otherwise', () => {
    expect(intervalOf(q.jobs, [makeJob({ state: 'running' })])).toBe(2_000)
    expect(intervalOf(q.jobs, [makeJob({ state: 'failed' })])).toBe(15_000)
    expect(intervalOf(q.jobs, undefined)).toBe(15_000)
  })

  it('polls one job until it ends', () => {
    const o = q.job('j1')
    expect(intervalOf(o, undefined)).toBe(2_000)
    expect(intervalOf(o, makeJob({ state: 'running' }))).toBe(2_000)
    expect(intervalOf(o, makeJob({ state: 'succeeded' }))).toBe(false)
  })

  it('every query function reaches its endpoint', async () => {
    const mock = stubApi({
      'GET /api/status': {}, 'GET /api/stats': {}, 'GET /api/installed': {}, 'GET /api/library': {},
      'GET /api/commands': [], 'GET /api/setup': {}, 'GET /api/daemon': {}, 'GET /api/server': {},
      'GET /api/backups': [], 'GET /api/dataset': makeDataset(), 'GET /api/budget': makeBudget(),
      'GET /api/jobs': [], 'GET /api/jobs/j1': makeJob(),
    })
    const all = [q.status, q.stats, q.installed, q.library, q.commands, q.setup, q.daemon, q.server,
      q.backups, q.dataset, q.budget, q.jobs, q.job('j1')]
    for (const o of all) await queryClient.fetchQuery({ ...o, retry: false, staleTime: 0 })
    expect(mock).toHaveBeenCalledTimes(all.length)
  })

  it('refreshAfterJob invalidates everything', async () => {
    stubApi({ 'GET /api/server': { stale: false } })
    const obs = new QueryObserver(queryClient, { ...q.server, refetchInterval: false })
    const unsub = obs.subscribe(() => {})
    await vi.waitFor(() => expect(obs.getCurrentResult().isSuccess).toBe(true))
    const spy = vi.spyOn(queryClient, 'invalidateQueries')
    refreshAfterJob()
    expect(spy).toHaveBeenCalled()
    unsub()
  })
})
