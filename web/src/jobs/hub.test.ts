import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource, installEventSource } from '../test/harness'
import { hub } from './hub'

let n = 0
const newId = () => `hub-job-${++n}`
const ts = '2026-10-10T10:00:00Z'

describe('JobHub', () => {
  beforeEach(() => {
    installEventSource()
    document.head.innerHTML = '<meta name="sbe-token" content="t&k">'
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    hub.onTerminal = () => {}
  })

  it('reports an empty job before anything arrives', () => {
    expect(hub.get(newId())).toMatchObject({ lastSeq: 0, state: null, logs: [], connected: false })
  })

  it('opens one stream per job, sharing it between watchers', () => {
    const id = newId()
    const a = hub.watch(id)
    const b = hub.watch(id)
    expect(FakeEventSource.all).toHaveLength(1)
    expect(FakeEventSource.last.url).toBe(`/api/jobs/${id}/events?token=t%26k&after=0`)
    a()
    expect(FakeEventSource.last.closed).toBe(false)
    b()
    expect(FakeEventSource.last.closed).toBe(true)
  })

  it('marks the stream connected on open and disconnected on release', () => {
    const id = newId()
    const unwatch = hub.watch(id)
    FakeEventSource.last.onopen?.()
    expect(hub.get(id).connected).toBe(true)
    unwatch()
    expect(hub.get(id).connected).toBe(false)
  })

  it('notifies subscribers, until they unsubscribe', () => {
    const id = newId()
    const listener = vi.fn()
    const off = hub.subscribe(listener)
    const unwatch = hub.watch(id)
    FakeEventSource.last.emit('log', { seq: 1, ts, type: 'log', level: 'info', message: 'hi' })
    expect(listener).toHaveBeenCalledTimes(1)
    off()
    FakeEventSource.last.emit('log', { seq: 2, ts, type: 'log', level: 'info', message: 'again' })
    expect(listener).toHaveBeenCalledTimes(1)
    unwatch()
  })

  it('folds state, log, progress, prompt and result events', () => {
    const id = newId()
    const unwatch = hub.watch(id)
    const es = FakeEventSource.last
    es.emit('state', { seq: 1, ts, type: 'state', state: 'running' })
    es.emit('log', { seq: 2, ts, type: 'log', level: 'warning', message: 'careful' })
    es.emit('progress', { seq: 3, ts, type: 'progress', step: 1, total: 4, label: 'Scanning', item: 'A', eta_seconds: 9 })
    const first = hub.get(id).startedProgressAt
    es.emit('progress', { seq: 4, ts, type: 'progress', step: 2, total: 4, label: 'Scanning' })
    expect(hub.get(id).startedProgressAt).toBe(first)
    expect(hub.get(id).progress).toMatchObject({ step: 2, label: 'Scanning' })
    es.emit('prompt', { seq: 5, ts, type: 'prompt', prompt_id: 'q1', kind: 'confirm', message: 'ok?' })
    es.emit('state', { seq: 6, ts, type: 'state', state: 'waiting_input' })
    expect(hub.get(id).prompt?.prompt_id).toBe('q1')
    es.emit('state', { seq: 7, ts, type: 'state', state: 'running' })
    expect(hub.get(id).prompt).toBeNull()
    es.emit('prompt', { seq: 8, ts, type: 'prompt', prompt_id: 'q2', kind: 'text', message: 'name?' })
    es.emit('result', { seq: 9, ts, type: 'result', ok: true, summary: 'done' })
    const live = hub.get(id)
    expect(live).toMatchObject({ state: 'running', prompt: null, lastSeq: 9 })
    expect(live.logs.map((l) => l.message)).toEqual(['careful'])
    expect(live.result?.summary).toBe('done')
    unwatch()
  })

  it('keeps only the most recent 500 log lines', () => {
    const id = newId()
    const unwatch = hub.watch(id)
    for (let i = 1; i <= 505; i++) FakeEventSource.last.emit('log', { seq: i, ts, type: 'log', level: 'info', message: `m${i}` })
    const logs = hub.get(id).logs
    expect(logs).toHaveLength(500)
    expect(logs[0].message).toBe('m6')
    unwatch()
  })

  it('accepts unnamed messages, drops replays and ignores junk', () => {
    const id = newId()
    const unwatch = hub.watch(id)
    const es = FakeEventSource.last
    es.emitRaw(JSON.stringify({ seq: 1, ts, type: 'log', level: 'info', message: 'one' }))
    es.emitRaw(JSON.stringify({ seq: 1, ts, type: 'log', level: 'info', message: 'dup' }))
    es.emitRaw('{not json')
    expect(hub.get(id).logs.map((l) => l.message)).toEqual(['one'])
    unwatch()
  })

  it('tells onTerminal when a job ends, by state or by result', () => {
    const onTerminal = vi.fn()
    hub.onTerminal = onTerminal
    const id = newId()
    const unwatch = hub.watch(id)
    FakeEventSource.last.emit('state', { seq: 1, ts, type: 'state', state: 'running' })
    expect(onTerminal).not.toHaveBeenCalled()
    FakeEventSource.last.emit('state', { seq: 2, ts, type: 'state', state: 'failed' })
    FakeEventSource.last.emit('result', { seq: 3, ts, type: 'result', ok: false, summary: 'x' })
    expect(onTerminal).toHaveBeenCalledTimes(2)
    expect(onTerminal).toHaveBeenCalledWith(id)
    unwatch()
  })

  it('has a harmless default for onTerminal', async () => {
    vi.resetModules()
    const { hub: fresh } = await import('./hub')
    const unwatch = fresh.watch('fresh-job')
    FakeEventSource.last.emit('state', { seq: 1, ts, type: 'state', state: 'succeeded' })
    expect(fresh.get('fresh-job').state).toBe('succeeded')
    unwatch()
  })

  it('answered hides only the prompt it answered', () => {
    const id = newId()
    const unwatch = hub.watch(id)
    FakeEventSource.last.emit('prompt', { seq: 1, ts, type: 'prompt', prompt_id: 'q1', kind: 'text', message: '?' })
    hub.answered(id, 'other')
    expect(hub.get(id).prompt).not.toBeNull()
    hub.answered(id, 'q1')
    expect(hub.get(id).prompt).toBeNull()
    unwatch()
  })

  it('does not reopen a stream for a job that already finished', () => {
    const id = newId()
    const first = hub.watch(id)
    FakeEventSource.last.emit('state', { seq: 1, ts, type: 'state', state: 'succeeded' })
    FakeEventSource.last.emit('result', { seq: 2, ts, type: 'result', ok: true, summary: 's' })
    first()
    const opened = FakeEventSource.all.length
    hub.watch(id)()
    expect(FakeEventSource.all).toHaveLength(opened)
  })

  describe('reconnecting', () => {
    beforeEach(() => vi.useFakeTimers())

    it('reopens after the last seen event, with growing backoff, reset by a good open', () => {
      const id = newId()
      const unwatch = hub.watch(id)
      FakeEventSource.last.emit('log', { seq: 7, ts, type: 'log', level: 'info', message: 'x' })
      FakeEventSource.last.onerror?.()
      expect(FakeEventSource.last.closed).toBe(true)
      expect(hub.get(id).connected).toBe(false)
      vi.advanceTimersByTime(999)
      expect(FakeEventSource.all).toHaveLength(1)
      vi.advanceTimersByTime(1)
      expect(FakeEventSource.all).toHaveLength(2)
      expect(FakeEventSource.last.url).toMatch(/after=7$/)
      FakeEventSource.last.onerror?.() // second failure: 2 s
      vi.advanceTimersByTime(1999)
      expect(FakeEventSource.all).toHaveLength(2)
      vi.advanceTimersByTime(1)
      expect(FakeEventSource.all).toHaveLength(3)
      FakeEventSource.last.onopen?.()
      FakeEventSource.last.onerror?.() // backoff is back to 1 s
      vi.advanceTimersByTime(1000)
      expect(FakeEventSource.all).toHaveLength(4)
      unwatch()
    })

    it('caps the backoff at ten seconds', () => {
      const id = newId()
      const unwatch = hub.watch(id)
      for (let i = 0; i < 6; i++) {
        FakeEventSource.last.onerror?.()
        vi.advanceTimersByTime(10_000)
      }
      expect(FakeEventSource.all).toHaveLength(7)
      FakeEventSource.last.onerror?.()
      vi.advanceTimersByTime(9_999)
      expect(FakeEventSource.all).toHaveLength(7)
      vi.advanceTimersByTime(1)
      expect(FakeEventSource.all).toHaveLength(8)
      unwatch()
    })

    it('does not retry a finished job', () => {
      const id = newId()
      const unwatch = hub.watch(id)
      FakeEventSource.last.emit('state', { seq: 1, ts, type: 'state', state: 'cancelled' })
      FakeEventSource.last.onerror?.()
      vi.advanceTimersByTime(60_000)
      expect(FakeEventSource.all).toHaveLength(1)
      unwatch()
    })

    it('does not retry once nobody watches, and cancels a pending retry', () => {
      const id = newId()
      const unwatch = hub.watch(id)
      const es = FakeEventSource.last
      es.onerror?.() // retry scheduled, source already null
      unwatch() // clears the timer
      vi.advanceTimersByTime(60_000)
      expect(FakeEventSource.all).toHaveLength(1)
      es.onerror?.() // a late error on the dead source
      vi.advanceTimersByTime(60_000)
      expect(FakeEventSource.all).toHaveLength(1)
    })
  })
})
