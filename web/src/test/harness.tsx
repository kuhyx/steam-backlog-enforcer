// Test harness: a routed fetch stub, a fake EventSource and a render helper
// that provides the query client and a memory-history router. Lives under
// src/test/, excluded from the app build and from coverage.

import { QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'
import { queryClient } from '../api/queries'

export interface Req {
  method: string
  path: string
  body: unknown
}
/** A value, or a function of the request that may return a value, a Reply or a Promise. */
type Handler = unknown | ((r: Req) => unknown)

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

export const apiError = (status: number, error: string, message = '') =>
  new Reply(status, { error, message })

async function respond(h: Handler, req: Req) {
  const out = await (typeof h === 'function' ? (h as (r: Req) => unknown)(req) : h)
  const r = out instanceof Reply ? out : new Reply(200, out)
  const text = r.raw ?? (r.body === undefined ? '' : JSON.stringify(r.body))
  const ok = r.status < 400
  return {
    ok,
    status: r.status,
    statusText: ok ? 'OK' : 'Error',
    text: async () => text,
    json: async () => JSON.parse(text) as unknown,
  }
}

/**
 * Stub `fetch` with `{ 'GET /api/status': value | (req) => value | Reply }`.
 * Lookup is per call, so a test may edit `routes` between steps. A missing
 * route is a network failure, which makes an unmocked call visible.
 */
export function stubApi(routes: Record<string, Handler>) {
  const mock = vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined
    const bare = path.split('?')[0]
    const key = [`${method} ${path}`, `${method} ${bare}`].find((k) => k in routes)
    if (!key) throw new Error(`unmocked ${method} ${path}`)
    return respond(routes[key], { method, path, body })
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** Bodies of the calls made to one route, in order. */
export function bodiesOf(mock: ReturnType<typeof stubApi>, key: string): unknown[] {
  return mock.mock.calls
    .filter(([p, init]) => `${init?.method ?? 'GET'} ${p}` === key)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : undefined))
}

type Listener = (e: { data: string }) => void

export class FakeEventSource {
  static all: FakeEventSource[] = []
  static get last(): FakeEventSource {
    return FakeEventSource.all[FakeEventSource.all.length - 1]
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

export const SECTION_PATHS = [
  '/', '/backlog', '/picks', '/gaming', '/library', '/store', '/jobs', '/jobs/$jobId', '/system', '/setup',
]

/** Render `ui` inside the query client and a memory router at `at`. */
export function renderRouted(ui: ReactNode, at = '/') {
  const root = createRootRoute({ component: () => ui })
  const children = SECTION_PATHS.map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => null }),
  )
  const router = createRouter({
    routeTree: root.addChildren(children),
    history: createMemoryHistory({ initialEntries: [at] }),
  })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, ...view }
}

/** Render `ui` inside the query client only (no router needed). */
export function renderClient(ui: ReactNode) {
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
