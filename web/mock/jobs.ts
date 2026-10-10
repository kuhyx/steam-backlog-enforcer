// In-memory job engine for the mock: jobs emit JobEvents over time, block on
// prompts until `POST …/answer` arrives, and keep their history so a page
// reload (or SSE reconnect with `after=`) replays exactly what was missed.

import { randomUUID } from 'node:crypto'
import type { CommandName } from '../src/api/contract.ts'
import type { Job, JobEvent, JobState, PromptKind, PromptOption } from '../src/api/jobContract.ts'

type Listener = (e: JobEvent) => void
type EventBody = JobEvent extends infer E ? (E extends JobEvent ? Omit<E, 'seq' | 'ts'> : never) : never

export interface MockJob {
  job: Job
  events: JobEvent[]
  listeners: Set<Listener>
  waiting: Map<string, (value: string) => void>
  cancelled: boolean
  mutating: boolean
}

export class Cancelled extends Error {}

export interface JobCtx {
  params: Record<string, number | string>
  log(message: string, level?: 'info' | 'warning' | 'error'): void
  progress(step: number, total: number | null, label: string, item?: string, eta?: number): void
  prompt(
    kind: PromptKind,
    message: string,
    extra?: { options?: PromptOption[]; phrase?: string; default?: string; app_ids?: number[] },
  ): Promise<string>
  sleep(ms: number): Promise<void>
}

export type Script = (ctx: JobCtx) => Promise<{ summary: string; ok?: boolean; data?: unknown }>

const TERMINAL: ReadonlySet<JobState> = new Set(['succeeded', 'failed', 'cancelled'])
export const jobs = new Map<string, MockJob>()

export function isTerminal(state: JobState): boolean {
  return TERMINAL.has(state)
}

export function runningMutating(): MockJob | undefined {
  return [...jobs.values()].find((j) => j.mutating && !isTerminal(j.job.state))
}

function emit(mj: MockJob, body: EventBody): void {
  const event = { ...body, seq: mj.events.length + 1, ts: new Date().toISOString() } as JobEvent
  mj.events.push(event)
  if (event.type === 'state') {
    mj.job.state = event.state
    if (event.state === 'running' && mj.job.started_at === null) mj.job.started_at = event.ts
    if (isTerminal(event.state)) mj.job.ended_at = event.ts
  } else if (event.type === 'progress') {
    const { step, total, label, item, eta_seconds } = event
    mj.job.progress = { step, total, label, item, eta_seconds }
  } else if (event.type === 'result') {
    mj.job.summary = event.summary
    mj.job.exit_code = event.ok ? 0 : 1
  }
  for (const l of mj.listeners) l(event)
}

export function startJob(
  command: CommandName,
  params: Record<string, number | string>,
  script: Script,
  mutating: boolean,
): Job {
  const job: Job = {
    id: randomUUID().slice(0, 8),
    command,
    params,
    state: 'queued',
    created_at: new Date().toISOString(),
    started_at: null,
    ended_at: null,
    exit_code: null,
    progress: null,
    summary: null,
  }
  const mj: MockJob = { job, events: [], listeners: new Set(), waiting: new Map(), cancelled: false, mutating }
  jobs.set(job.id, mj)
  emit(mj, { type: 'state', state: 'queued' })
  void run(mj, script)
  return { ...job }
}

async function run(mj: MockJob, script: Script): Promise<void> {
  const sleep = (ms: number) =>
    new Promise<void>((resolve, reject) => {
      setTimeout(() => (mj.cancelled ? reject(new Cancelled()) : resolve()), ms)
    })
  let n = 0
  const ctx: JobCtx = {
    params: mj.job.params,
    log: (message, level = 'info') => emit(mj, { type: 'log', level, message }),
    progress: (step, total, label, item, eta) =>
      emit(mj, { type: 'progress', step, total, label, item, eta_seconds: eta }),
    prompt: (kind, message, extra = {}) => {
      n += 1
      const prompt_id = `p${n}`
      emit(mj, { type: 'state', state: 'waiting_input' })
      emit(mj, { type: 'prompt', prompt_id, kind, message, ...extra })
      return new Promise<string>((resolve) => {
        mj.waiting.set(prompt_id, (value) => {
          mj.waiting.delete(prompt_id)
          emit(mj, { type: 'state', state: 'running' })
          resolve(value)
        })
      })
    },
    sleep,
  }
  try {
    await sleep(400)
    emit(mj, { type: 'state', state: 'running' })
    const { summary, ok = true, data } = await script(ctx)
    emit(mj, { type: 'result', ok, summary, data })
    emit(mj, { type: 'state', state: ok ? 'succeeded' : 'failed' })
  } catch (e) {
    if (e instanceof Cancelled) {
      emit(mj, { type: 'log', level: 'warning', message: 'Cancelled by user.' })
      emit(mj, { type: 'result', ok: false, summary: 'Cancelled before it finished.' })
      emit(mj, { type: 'state', state: 'cancelled' })
    } else {
      emit(mj, { type: 'log', level: 'error', message: String(e) })
      emit(mj, { type: 'result', ok: false, summary: e instanceof Error ? e.message : String(e) })
      emit(mj, { type: 'state', state: 'failed' })
    }
  }
}

export function answer(id: string, promptId: string, value: string): boolean {
  const resolve = jobs.get(id)?.waiting.get(promptId)
  if (!resolve) return false
  resolve(value)
  return true
}

export function cancel(id: string): void {
  const mj = jobs.get(id)
  if (!mj || isTerminal(mj.job.state)) return
  mj.cancelled = true
  // A job blocked on a prompt has no sleep to wake; release it.
  for (const resolve of [...mj.waiting.values()]) resolve('')
}

export function listJobs(): Job[] {
  return [...jobs.values()].map((j) => ({ ...j.job })).reverse().slice(0, 50)
}
