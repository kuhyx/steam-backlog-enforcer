// `<job-progress job-id="…" [compact]>`: one job, live from its SSE stream
// (hub.ts) with the REST copy as fallback (was JobProgress.tsx). The frame is
// built once; each update refreshes the parts, appends only new log lines,
// and swaps the prompt form only when a new prompt arrives, so typing an
// answer or reading the log is never interrupted by a progress event.

import { api } from '../api/client'
import type { JobProgress as Progress, JobState } from '../api/jobContract'
import { q } from '../api/queries'
import { commandLabel, findCommand } from '../commands/catalog'
import { Action } from '../lib/action'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { errorNotice, notice } from '../ui/build'
import { clock, duration } from '../ui/format'
import { hub, type LiveJob } from './hub'
import { progressBar, stateBadge } from './progress'
import { promptForm } from './promptForm'

/** Remaining seconds: the job's own estimate, else extrapolated from pace. */
export function eta(p: Progress, live: LiveJob, now: number): number | null {
  if (typeof p.eta_seconds === 'number') return p.eta_seconds
  if (p.total === null || p.step <= 0 || live.startedProgressAt === null) return null
  const perStep = (now / 1000 - live.startedProgressAt) / p.step
  return perStep * (p.total - p.step)
}

const DONE: ReadonlySet<JobState> = new Set(['succeeded', 'failed', 'cancelled'])
const FINISHED_LABEL: Record<'succeeded' | 'failed' | 'cancelled', string> = {
  succeeded: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}
const isDone = (s: JobState): s is keyof typeof FINISHED_LABEL => DONE.has(s)

export class JobProgressElement extends LiveElement {
  private cancel = new Action(() => api.cancelJob(this.jobId), () => {
    this.update()
  })
  private frame: {
    section: HTMLElement
    title: HTMLHeadingElement
    badge: HTMLSpanElement
    meta: HTMLSpanElement
    phase: HTMLDivElement
    bar: HTMLDivElement
    sub: HTMLDivElement
    prompt: HTMLDivElement
    result: HTMLDivElement
    actions: HTMLDivElement
    log: HTMLOListElement
    details: HTMLDetailsElement
    summary: HTMLElement
  } | null = null
  private promptId: string | null = null
  private logCount = -1
  private autoOpened = false

  get jobId(): string {
    return this.getAttribute('job-id') ?? ''
  }

  protected override setup(): void {
    const id = this.jobId
    this.onCleanup(hub.watch(id))
    this.onCleanup(hub.subscribe(() => {
      this.update()
    }))
    this.watch(q.job(id))
    this.watch(q.commands)
    this.tick(1000)
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback()
    this.frame = null
    this.promptId = null
    this.logCount = -1
    this.autoOpened = false
  }

  private build(): NonNullable<JobProgressElement['frame']> {
    const f = {
      title: h('h3', { class: 'job-title' }),
      badge: h('span'),
      meta: h('span', { class: 'job-meta' }),
      phase: h('div', { class: 'job-phase', 'aria-live': 'polite' }),
      bar: h('div', { class: 'contents' }),
      sub: h('div', { class: 'contents' }),
      prompt: h('div', { class: 'contents' }),
      result: h('div', { class: 'contents' }),
      actions: h('div', { class: 'contents' }),
      log: h('ol', { class: 'log', tabindex: 0, 'aria-label': 'Job log' }),
      summary: h('summary'),
      details: h('details', { class: 'job-log' }),
      section: h('section'),
    }
    f.details.append(f.summary, f.log)
    f.section.append(
      h('div', { class: 'job-head' }, f.title, f.badge, f.meta),
      f.phase,
      f.bar,
      f.sub,
      f.prompt,
      f.result,
      f.actions,
      f.details,
    )
    this.replaceChildren(f.section)
    return f
  }

  protected update(): void {
    const id = this.jobId
    const live = hub.get(id)
    const job = q.job(id).state.data
    const f = (this.frame ??= this.build())
    const compact = this.hasAttribute('compact')
    const now = Date.now()
    const state: JobState = live.state ?? job?.state ?? 'queued'
    const progress = live.progress ?? job?.progress ?? null
    const finished = DONE.has(state)
    const waiting = state === 'waiting_input'
    const spec = job ? findCommand(q.commands.state.data, job.command) : undefined
    const fraction = finished ? 1 : progress && progress.total !== null && progress.total > 0 ? progress.step / progress.total : null
    const tone = state === 'failed' ? 'danger' : state === 'succeeded' ? 'success' : waiting ? 'warning' : 'accent'
    const remaining = progress && !finished && !waiting ? eta(progress, live, now) : null
    const title = job ? commandLabel(job.command) : 'Job'

    f.section.className = compact ? 'job job-compact' : 'job'
    f.section.setAttribute('aria-label', `Job ${job ? commandLabel(job.command) : id}`)
    f.title.textContent = title
    f.badge.replaceChildren(stateBadge(state))
    f.meta.replaceChildren(
      job ? duration(job.started_at, job.ended_at, now) : '',
      finished
        ? ''
        : h(
            'span',
            { class: live.connected ? 'dot dot-live' : 'dot dot-off', title: live.connected ? 'Live' : 'Reconnecting…' },
            h('span', { class: 'sr-only' }, live.connected ? 'Live' : 'Reconnecting'),
          ),
    )
    f.phase.replaceChildren(
      h(
        'span',
        { class: 'job-label' },
        isDone(state) ? FINISHED_LABEL[state] : waiting ? 'Waiting for your answer' : (progress?.label ?? 'Starting…'),
      ),
      !finished && progress && progress.total !== null
        ? h('span', { class: 'job-step' }, `Step ${progress.step} of ${progress.total}`)
        : '',
    )
    f.bar.replaceChildren(progressBar(fraction, progress?.label ?? 'Progress', tone))
    f.sub.replaceChildren(
      ...(finished
        ? []
        : [
            h(
              'div',
              { class: 'job-sub' },
              h('span', { class: 'job-item' }, progress?.item ?? ' '),
              h(
                'span',
                { class: 'job-eta' },
                remaining !== null ? `about ${clock(remaining)} left` : waiting ? 'paused' : progress?.total === null ? 'working…' : '',
              ),
            ),
          ]),
    )
    this.updatePrompt(f, live, state)
    f.result.replaceChildren(
      ...(live.result
        ? [notice(live.result.ok ? 'success' : 'danger', live.result.ok ? 'Done' : 'Did not complete', live.result.summary)]
        : []),
    )
    f.actions.replaceChildren(
      ...(this.cancel.error ? [errorNotice(this.cancel.error)] : []),
      ...((spec?.cancellable || waiting) && !finished
        ? [
            h(
              'div',
              { class: 'actions' },
              h(
                'button',
                { type: 'button', class: 'btn btn-ghost', disabled: this.cancel.pending, onclick: () => void this.cancel.run() },
                this.cancel.pending ? 'Cancelling…' : 'Cancel job',
              ),
            ),
          ]
        : []),
    )
    this.updateLog(f, live, finished, compact)
  }

  private updatePrompt(f: NonNullable<JobProgressElement['frame']>, live: LiveJob, state: JobState): void {
    const prompt = live.prompt && state === 'waiting_input' ? live.prompt : null
    const id = prompt?.prompt_id ?? null
    if (id === this.promptId) return
    this.promptId = id
    f.prompt.replaceChildren(...(prompt ? [promptForm(this.jobId, prompt)] : []))
    f.prompt.querySelector<HTMLElement>('[autofocus]')?.focus()
  }

  private updateLog(f: NonNullable<JobProgressElement['frame']>, live: LiveJob, finished: boolean, compact: boolean): void {
    const logs = live.logs
    f.summary.textContent = `Log (${logs.length} lines)`
    // Open once on errors or at the end; after that the user owns the toggle.
    if (!this.autoOpened && !compact && (finished || logs.some((l) => l.level === 'error'))) {
      f.details.open = true
      this.autoOpened = true
    }
    if (logs.length === 0) {
      f.log.replaceChildren(h('li', { class: 'muted' }, finished ? 'No output.' : 'No output yet.'))
      this.logCount = 0
      return
    }
    // The hub keeps the newest MAX_LOGS lines; rebuild when the window slid.
    const first = f.log.firstElementChild as HTMLElement | null
    const slid = this.logCount <= 0 || first?.dataset.seq !== String(logs[0]?.seq)
    const fresh = slid ? logs : logs.slice(this.logCount)
    if (slid) f.log.replaceChildren()
    for (const l of fresh) {
      const li = h('li', { class: `log-${l.level}` }, h('time', { datetime: l.ts }, l.ts.slice(11, 19)), ` ${l.message}`)
      li.dataset.seq = String(l.seq)
      f.log.append(li)
    }
    if (fresh.length) f.log.scrollTop = f.log.scrollHeight
    this.logCount = logs.length
  }
}

define('job-progress', JobProgressElement)
