import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBudget, makeDataset } from '../test/factories'
import { makeJob } from '../test/fixtures'
import { apiError, Reply, stubApi, type Handler } from '../test/harness'
import { isActive, q, refreshAfterJob } from './queries'

describe('queries', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('isActive is false only for terminal states', () => {
    expect(isActive(makeJob({ state: 'running' }))).toBe(true)
    expect(isActive(makeJob({ state: 'waiting_input' }))).toBe(true)
    expect(isActive(makeJob({ state: 'succeeded' }))).toBe(false)
    expect(isActive(makeJob({ state: 'failed' }))).toBe(false)
    expect(isActive(makeJob({ state: 'cancelled' }))).toBe(false)
  })

  it('every query reaches its endpoint', async () => {
    const mock = stubApi({
      'GET /api/status': {}, 'GET /api/stats': {}, 'GET /api/installed': {}, 'GET /api/library': {},
      'GET /api/commands': [], 'GET /api/setup': {}, 'GET /api/daemon': {}, 'GET /api/server': {},
      'GET /api/backups': [], 'GET /api/dataset': makeDataset(), 'GET /api/budget': makeBudget(),
      'GET /api/budget?demo=1': makeBudget(), 'GET /api/jobs': [], 'GET /api/jobs/j1': makeJob(),
    })
    const all = [q.status, q.stats, q.installed, q.library, q.commands, q.setup, q.daemon, q.server,
      q.backups, q.dataset, q.budget, q.demoBudget, q.jobs, q.job('j1')]
    for (const query of all) await query.refetch()
    expect(mock).toHaveBeenCalledTimes(all.length)
    expect(all.every((query) => query.state.error === null)).toBe(true)
  })

  it('polls jobs fast while one is active, slowly otherwise', async () => {
    const jobs = [makeJob({ state: 'running' })]
    const mock = stubApi({ 'GET /api/jobs': () => jobs })
    q.jobs.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(mock).toHaveBeenCalledTimes(2)
    jobs[0] = makeJob({ state: 'failed' })
    await vi.advanceTimersByTimeAsync(2000)
    expect(mock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(14_000)
    expect(mock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1000)
    expect(mock).toHaveBeenCalledTimes(4)
  })

  it('polls jobs slowly while nothing has loaded', async () => {
    const mock = stubApi({ 'GET /api/jobs': apiError(500, 'op_failed') })
    q.jobs.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(14_999)
    expect(mock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  it('polls one job until it ends', async () => {
    let job = makeJob({ state: 'running' })
    const mock = stubApi({ 'GET /api/jobs/j9': () => job })
    q.job('j9').subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(mock).toHaveBeenCalledTimes(2)
    job = makeJob({ state: 'succeeded' })
    await vi.advanceTimersByTimeAsync(2000)
    expect(mock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mock).toHaveBeenCalledTimes(3)
  })

  it('keeps polling a job whose first answer failed', async () => {
    const mock = stubApi({ 'GET /api/jobs/j8': apiError(404, 'not_found') })
    q.job('j8').subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(2000)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  it('refreshAfterJob refetches every watched query', async () => {
    const mock = stubApi({ 'GET /api/server': { stale: false } })
    q.server.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    refreshAfterJob()
    await vi.advanceTimersByTimeAsync(0)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  describe('budget polling', () => {
    const setHidden = (hidden: boolean) => {
      Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
    }
    afterEach(() => {
      setHidden(false)
    })

    it('polls the budget every 5 s, the demo run from its own URL', async () => {
      const mock = stubApi({ 'GET /api/budget': makeBudget(), 'GET /api/budget?demo=1': makeBudget() })
      q.budget.subscribe(() => undefined)
      q.demoBudget.subscribe(() => undefined)
      await vi.advanceTimersByTimeAsync(0)
      expect(mock.mock.calls.map(([p]) => p)).toEqual(['/api/budget', '/api/budget?demo=1'])
      await vi.advanceTimersByTimeAsync(5000)
      expect(mock).toHaveBeenCalledTimes(4)
      expect(q.budget.state.data?.today?.gaming_day).toBe('2026-08-28')
    })

    it('polls while the tab is hidden', async () => {
      setHidden(true)
      const mock = stubApi({ 'GET /api/budget': makeBudget() })
      q.budget.subscribe(() => undefined)
      await vi.advanceTimersByTimeAsync(10_000)
      expect(mock).toHaveBeenCalledTimes(3)
    })

    it('keeps the last snapshot when a poll fails', async () => {
      const routes: Record<string, Handler> = { 'GET /api/budget': makeBudget() }
      stubApi(routes)
      q.budget.subscribe(() => undefined)
      await vi.advanceTimersByTimeAsync(0)
      routes['GET /api/budget'] = new Reply(500, undefined, 'oops')
      await vi.advanceTimersByTimeAsync(5000)
      expect(q.budget.state.data?.ok).toBe(true)
      expect(q.budget.state.error).toEqual(new Error('API returned 500 Error'))
    })

    it('stops polling after the last subscriber leaves', async () => {
      const mock = stubApi({ 'GET /api/budget': makeBudget() })
      const off = q.budget.subscribe(() => undefined)
      await vi.advanceTimersByTimeAsync(0)
      off()
      await vi.advanceTimersByTimeAsync(20_000)
      expect(mock).toHaveBeenCalledTimes(1)
    })
  })
})
