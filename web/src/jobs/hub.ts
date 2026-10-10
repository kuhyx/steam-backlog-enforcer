// Live job state from `GET /api/jobs/{id}/events` (SSE). One EventSource per
// watched job, shared by every component showing it. On a dropped stream the
// source is closed (so the browser's own retry, which knows nothing about
// `after=`, never fires) and reopened with `after=<last seq>`.

import { sessionToken } from '../api/client'
import {
  ENDPOINTS,
} from '../api/contract'
import type { JobEvent, JobProgress, JobState } from '../api/jobContract'

export type PromptEvent = Extract<JobEvent, { type: 'prompt' }>
export type LogEvent = Extract<JobEvent, { type: 'log' }>
export type ResultEvent = Extract<JobEvent, { type: 'result' }>

export interface LiveJob {
  lastSeq: number
  state: JobState | null
  progress: JobProgress | null
  logs: LogEvent[]
  /** Prompt the job is blocked on, until answered here or resumed. */
  prompt: PromptEvent | null
  result: ResultEvent | null
  connected: boolean
  /** Seconds since epoch of the first progress event, for rate display. */
  startedProgressAt: number | null
}

const EMPTY: LiveJob = {
  lastSeq: 0, state: null, progress: null, logs: [], prompt: null, result: null,
  connected: false, startedProgressAt: null,
}
const TERMINAL = new Set<JobState>(['succeeded', 'failed', 'cancelled'])
const EVENT_TYPES = ['state', 'log', 'progress', 'prompt', 'result'] as const
const MAX_LOGS = 500

function reduce(live: LiveJob, e: JobEvent): LiveJob {
  const next: LiveJob = { ...live, lastSeq: e.seq }
  switch (e.type) {
    case 'state':
      next.state = e.state
      if (e.state !== 'waiting_input') next.prompt = null
      break
    case 'log':
      next.logs = [...live.logs, e].slice(-MAX_LOGS)
      break
    case 'progress': {
      const { step, total, label, item, eta_seconds } = e
      next.progress = { step, total, label, item, eta_seconds }
      next.startedProgressAt ??= Date.now() / 1000
      break
    }
    case 'prompt':
      next.prompt = e
      break
    case 'result':
      next.result = e
      next.prompt = null
      break
  }
  return next
}

interface Stream {
  refs: number
  source: EventSource | null
  retry: ReturnType<typeof setTimeout> | null
  backoff: number
}

class JobHub {
  private live = new Map<string, LiveJob>()
  private streams = new Map<string, Stream>()
  private listeners = new Set<() => void>()
  onTerminal: (id: string) => void = () => {}

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  get(id: string): LiveJob {
    return this.live.get(id) ?? EMPTY
  }

  /** Start following a job; returns the matching unwatch. Ref-counted. */
  watch(id: string): () => void {
    const s = this.streams.get(id) ?? { refs: 0, source: null, retry: null, backoff: 1000 }
    s.refs += 1
    this.streams.set(id, s)
    if (s.refs === 1) this.open(id, s)
    return () => {
      s.refs -= 1
      if (s.refs > 0) return
      s.source?.close()
      if (s.retry) clearTimeout(s.retry)
      this.streams.delete(id)
      this.patch(id, { connected: false })
    }
  }

  /** Hide an answered prompt immediately, before the job's state event. */
  answered(id: string, promptId: string): void {
    if (this.get(id).prompt?.prompt_id === promptId) this.patch(id, { prompt: null })
  }

  private open(id: string, s: Stream): void {
    const live = this.get(id)
    if (live.state && TERMINAL.has(live.state) && live.result) return
    const url = `${ENDPOINTS.jobEvents(id)}?token=${encodeURIComponent(sessionToken())}&after=${live.lastSeq}`
    const source = new EventSource(url)
    s.source = source
    const onEvent = (msg: MessageEvent<string>) => this.ingest(id, msg.data)
    source.onmessage = onEvent
    for (const t of EVENT_TYPES) source.addEventListener(t, onEvent)
    source.onopen = () => {
      s.backoff = 1000
      this.patch(id, { connected: true })
    }
    source.onerror = () => {
      source.close()
      s.source = null
      this.patch(id, { connected: false })
      const state = this.get(id).state
      if (state && TERMINAL.has(state)) return
      if (s.refs > 0) {
        s.retry = setTimeout(() => this.open(id, s), s.backoff)
        s.backoff = Math.min(s.backoff * 2, 10_000)
      }
    }
  }

  private ingest(id: string, data: string): void {
    let e: JobEvent
    try {
      e = JSON.parse(data) as JobEvent
    } catch {
      return
    }
    const live = this.get(id)
    if (e.seq <= live.lastSeq) return
    const next = reduce(live, e)
    this.live.set(id, next)
    this.emit()
    if ((e.type === 'state' && TERMINAL.has(e.state)) || e.type === 'result') this.onTerminal(id)
  }

  private patch(id: string, p: Partial<LiveJob>): void {
    this.live.set(id, { ...this.get(id), ...p })
    this.emit()
  }

  private emit(): void {
    for (const l of this.listeners) l()
  }
}

export const hub = new JobHub()
