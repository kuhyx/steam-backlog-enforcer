import { beforeEach, describe, expect, it, vi } from 'vitest'
import { family, invalidateAll, Query, resetAll } from './query'

function counting<T>(values: (() => T | Promise<T>)[]) {
  let calls = 0
  const fetcher = vi.fn(async () => {
    const make = values[Math.min(calls, values.length - 1)]
    calls += 1
    return make()
  })
  return fetcher
}

describe('Query', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('starts loading, fetches on first subscribe and notifies', async () => {
    const q = new Query(counting([() => 'a']))
    expect(q.state).toEqual({ data: undefined, error: null, loading: true })
    const seen = vi.fn()
    q.subscribe(seen)
    await vi.advanceTimersByTimeAsync(0)
    expect(q.state).toEqual({ data: 'a', error: null, loading: false })
    expect(seen).toHaveBeenCalledWith({ data: 'a', error: null, loading: false })
  })

  it('shares one fetch between subscribers and joins an in-flight refetch', async () => {
    const fetcher = counting([() => 'a'])
    const q = new Query(fetcher)
    q.subscribe(() => undefined)
    q.subscribe(() => undefined)
    void q.refetch()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('keeps the last good data when a refetch fails', async () => {
    const boom = new Error('x')
    const q = new Query(counting([() => 'ok', () => Promise.reject(boom)]))
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await q.refetch()
    expect(q.state).toEqual({ data: 'ok', error: boom, loading: false })
  })

  it('polls at a fixed interval while subscribed, and stops after unsubscribe', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs: 1000 })
    const off = q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(2)
    off()
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('keeps polling while another subscriber remains', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs: 100 })
    const first = q.subscribe(() => undefined)
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    first()
    await vi.advanceTimersByTimeAsync(100)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('takes the interval from a function of the data', async () => {
    const fetcher = counting([() => 5])
    const q = new Query(fetcher, { intervalMs: (d) => (d === 5 ? 200 : 900) })
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(200)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it.each<[false | undefined]>([[false], [undefined]])('does not poll when the interval is %s', async (intervalMs) => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs })
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('does not schedule when the last listener left during the fetch', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs: 100 })
    q.subscribe(() => undefined)()
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('reuses a fresh value on a new subscription, with the default or custom window', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs: 10_000 })
    q.subscribe(() => undefined)()
    await vi.advanceTimersByTimeAsync(0)
    q.subscribe(() => undefined)()
    expect(fetcher).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5001)
    q.subscribe(() => undefined)
    expect(fetcher).toHaveBeenCalledTimes(2)

    const slow = counting([() => 1])
    const q2 = new Query(slow, { staleMs: 60_000 })
    q2.subscribe(() => undefined)()
    await vi.advanceTimersByTimeAsync(30_000)
    q2.subscribe(() => undefined)
    expect(slow).toHaveBeenCalledTimes(1)
  })

  it('set() stores a value and notifies', () => {
    const q = new Query(counting([() => 'a']))
    const seen = vi.fn()
    q.subscribe(seen)
    seen.mockClear()
    q.set('b')
    expect(q.state).toEqual({ data: 'b', error: null, loading: false })
    expect(seen).toHaveBeenCalledTimes(1)
  })

  it('invalidate() refetches only when someone watches', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher)
    q.invalidate()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).not.toHaveBeenCalled()
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    q.invalidate()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('reset() forgets data, listeners and the poll timer', async () => {
    const fetcher = counting([() => 1])
    const q = new Query(fetcher, { intervalMs: 100 })
    const seen = vi.fn()
    q.subscribe(seen)
    await vi.advanceTimersByTimeAsync(0)
    q.reset()
    seen.mockClear()
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(seen).not.toHaveBeenCalled()
    expect(q.state).toEqual({ data: undefined, error: null, loading: true })
  })
})

describe('family', () => {
  it('makes one query per key', () => {
    const make = vi.fn((key: string) => new Query(() => Promise.resolve(key)))
    const by = family(make)
    expect(by('a')).toBe(by('a'))
    expect(by('b')).not.toBe(by('a'))
    expect(make).toHaveBeenCalledTimes(2)
  })
})

describe('registry', () => {
  it('invalidateAll refetches watched queries and resetAll clears them', async () => {
    vi.useFakeTimers()
    const fetcher = counting([() => 1])
    const q = new Query(fetcher)
    q.subscribe(() => undefined)
    await vi.advanceTimersByTimeAsync(0)
    invalidateAll()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(2)
    resetAll()
    expect(q.state.loading).toBe(true)
  })
})
