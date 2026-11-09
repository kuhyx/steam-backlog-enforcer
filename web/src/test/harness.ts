// Test harness: a routed fetch stub and a fake EventSource. Lives under
// src/test/, excluded from the app build and from coverage.

import { vi } from 'vitest'

export interface Req {
  method: string
  path: string
  body: unknown
}
/** A value, or a function of the request that may return a value, a Reply or a Promise. */
export type Handler = ((r: Req) => unknown) | object | string | number | boolean | null | undefined

/** A non-200 reply: `new Reply(409, { error: 'busy', message: '' })`. */
export class Reply {
  readonly status: number
  readonly body: unknown
  readonly raw: string | undefined
  constructor(status: number, body?: unknown, raw?: string) {
    this.status = status
    this.body = body
    this.raw = raw
  }
}

export const apiError = (status: number, error: string, message = '') => new Reply(status, { error, message })

async function respond(h: Handler, req: Req) {
  const out: unknown = await (typeof h === 'function' ? (h as (r: Req) => unknown)(req) : h)
  const r = out instanceof Reply ? out : new Reply(200, out)
  const text = r.raw ?? (r.body === undefined ? '' : JSON.stringify(r.body))
  const ok = r.status < 400
  return {
    ok,
    status: r.status,
    statusText: ok ? 'OK' : 'Error',
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text) as unknown),
  }
}

/**
 * Stub `fetch` with `{ 'GET /api/status': value | (req) => value | Reply }`.
 * Lookup is per call, so a test may edit `routes` between steps. A missing
 * route is a network failure, which makes an unmocked call visible.
 */
export function stubApi(routes: Record<string, Handler>) {
  const mock = vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined
    const bare = path.split('?')[0] ?? path
    const key = [`${method} ${path}`, `${method} ${bare}`].find((k) => k in routes)
    if (!key) return Promise.reject(new Error(`unmocked ${method} ${path}`))
    return respond(routes[key], { method, path, body })
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** Bodies of the calls made to one route, in order. */
export function bodiesOf(mock: ReturnType<typeof stubApi>, key: string): unknown[] {
  return mock.mock.calls
    .filter(([p, init]) => `${init?.method ?? 'GET'} ${p}` === key)
    .map(([, init]) => (typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined))
}

type Listener = (e: { data: string }) => void

export class FakeEventSource {
  static all: FakeEventSource[] = []
  static get last(): FakeEventSource {
    const last = FakeEventSource.all.at(-1)
    if (!last) throw new Error('no EventSource opened')
    return last
  }
  readonly url: string
  closed = false
  onopen: (() => void) | null = null
  onmessage: Listener | null = null
  onerror: (() => void) | null = null
  private listeners = new Map<string, Listener[]>()
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn])
  }
  close() {
    this.closed = true
  }
  /** Deliver a named event, as the server's SSE frames do. */
  emit(type: string, payload: unknown) {
    const ev = { data: JSON.stringify(payload) }
    for (const fn of this.listeners.get(type) ?? []) fn(ev)
  }
  emitRaw(data: string) {
    this.onmessage?.({ data })
  }
}

export function installEventSource() {
  FakeEventSource.all = []
  vi.stubGlobal('EventSource', FakeEventSource)
}

/** Let pending promise callbacks (fetch stubs, Action runs) settle. */
export async function flush(times = 5): Promise<void> {
  for (let i = 0; i < times; i++) await Promise.resolve()
}

/** Mount `html` into a fresh body and return the first element. */
export function mount(html: string): HTMLElement {
  document.body.innerHTML = html
  return document.body.firstElementChild as HTMLElement
}
