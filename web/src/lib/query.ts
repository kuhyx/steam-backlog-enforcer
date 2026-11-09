// A small replacement for React Query: one cached value per fetcher, fetched
// on first subscription, polled while anyone is subscribed, and refetched
// when invalidated. Polling deliberately ignores `document.hidden`:
// automation tabs and a Chrome --app window behind another report hidden,
// and a paused poll there shows frozen state.

export interface QueryState<T> {
  data: T | undefined
  error: unknown
  /** True until the first response (success or failure) arrives. */
  loading: boolean
}

export interface QueryOptions<T> {
  /** Poll period while subscribed; a function of the data, `false` = no poll. */
  intervalMs?: number | false | ((data: T | undefined) => number | false)
  /** A subscription within this long of the last fetch reuses it. */
  staleMs?: number
}

type Listener<T> = (state: QueryState<T>) => void

const registry = new Set<Query<unknown>>()

export class Query<T> {
  private current: QueryState<T> = { data: undefined, error: null, loading: true }
  private listeners = new Set<Listener<T>>()
  private timer: ReturnType<typeof setTimeout> | null = null
  private fetchedAt = 0
  private inflight: Promise<void> | null = null
  private readonly fetcher: () => Promise<T>
  private readonly opts: QueryOptions<T>

  constructor(fetcher: () => Promise<T>, opts: QueryOptions<T> = {}) {
    this.fetcher = fetcher
    this.opts = opts
    registry.add(this as Query<unknown>)
  }

  get state(): QueryState<T> {
    return this.current
  }

  /** Listen for changes; the first listener starts fetching and polling. */
  subscribe(listener: Listener<T>): () => void {
    this.listeners.add(listener)
    if (this.listeners.size === 1) {
      const fresh = this.fetchedAt > 0 && Date.now() - this.fetchedAt < (this.opts.staleMs ?? 5_000)
      if (fresh) this.schedule()
      else void this.refetch()
    }
    return () => {
      this.listeners.delete(listener)
      if (this.listeners.size === 0) this.stop()
    }
  }

  /** Fetch now (joining one already in flight) and notify listeners. */
  refetch(): Promise<void> {
    this.inflight ??= this.run().finally(() => {
      this.inflight = null
    })
    return this.inflight
  }

  /** Set the cached value locally, as a mutation's response does. */
  set(data: T): void {
    this.current = { data, error: null, loading: false }
    this.emit()
  }

  /** Mark stale; refetch now if anyone is watching. */
  invalidate(): void {
    this.fetchedAt = 0
    if (this.listeners.size > 0) void this.refetch()
  }

  /** Forget everything (tests). */
  reset(): void {
    this.stop()
    this.listeners.clear()
    this.current = { data: undefined, error: null, loading: true }
    this.fetchedAt = 0
    this.inflight = null
  }

  private async run(): Promise<void> {
    this.stop()
    try {
      const data = await this.fetcher()
      this.current = { data, error: null, loading: false }
    } catch (error) {
      // Keep the last good data: a failed poll should not blank the screen.
      this.current = { data: this.current.data, error, loading: false }
    }
    this.fetchedAt = Date.now()
    this.emit()
    this.schedule()
  }

  private schedule(): void {
    this.stop()
    if (this.listeners.size === 0) return
    const { intervalMs } = this.opts
    const ms = typeof intervalMs === 'function' ? intervalMs(this.current.data) : intervalMs
    if (ms === undefined || ms === false) return
    this.timer = setTimeout(() => void this.refetch(), ms)
  }

  private stop(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }

  private emit(): void {
    for (const l of [...this.listeners]) l(this.current)
  }
}

/** One Query per key, created on first use (e.g. a job by id). */
export function family<T>(make: (key: string) => Query<T>): (key: string) => Query<T> {
  const made = new Map<string, Query<T>>()
  return (key) => {
    let query = made.get(key)
    if (!query) {
      query = make(key)
      made.set(key, query)
    }
    return query
  }
}

/** After a job ends anything may have changed: refetch every watched query. */
export function invalidateAll(): void {
  for (const query of registry) query.invalidate()
}

/** Reset every query (tests). */
export function resetAll(): void {
  for (const query of registry) query.reset()
}
