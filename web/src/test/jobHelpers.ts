// Shared helpers for the <job-progress> tests. Lives under src/test/,
// excluded from the app build and from coverage.

import '../jobs/jobProgress'
import type { Job } from '../api/jobContract'
import { makeJob, makeSpec } from './fixtures'
import { FakeEventSource, stubApi, type Handler } from './harness'

export const TS = '2026-10-10T10:00:00Z'
let n = 0

export interface MountOptions {
  job?: Partial<Job>
  cancellable?: boolean
  compact?: boolean
  extra?: Record<string, Handler>
  attrs?: string
}

/** Mount `<job-progress>` for a fresh job id; `send` pushes SSE events into it. */
export function mountJob(opts: MountOptions = {}) {
  const id = `jp-${++n}`
  const routes: Record<string, Handler> = {
    [`GET /api/jobs/${id}`]: makeJob({ id, command: 'scan', ...opts.job }),
    'GET /api/commands': [makeSpec('scan', { cancellable: opts.cancellable ?? false })],
    ...opts.extra,
  }
  const mock = stubApi(routes)
  document.body.innerHTML = `<job-progress job-id="${id}" ${opts.compact ? 'compact' : ''} ${opts.attrs ?? ''}></job-progress>`
  const el = document.body.firstElementChild as HTMLElement
  const es = FakeEventSource.last
  let seq = 0
  const send = (type: string, body: Record<string, unknown>) => {
    es.emit(type, { seq: ++seq, ts: TS, type, ...body })
  }
  return { id, el, es, send, mock, routes }
}
