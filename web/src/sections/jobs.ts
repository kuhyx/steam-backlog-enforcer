// Jobs page (was screens/Jobs.tsx): `/jobs/` lists the job history,
// `/jobs/?id=<id>` shows one job live. Static output cannot prerender job
// ids, so one element picks its mode from the query string at connect.

import { ApiFailure } from '../api/client'
import { explain } from '../api/errors'
import type { Job } from '../api/jobContract'
import { q } from '../api/queries'
import { COMMAND_ICON, commandLabel } from '../commands/catalog'
import '../jobs/jobProgress'
import { stateBadge } from '../jobs/progress'
import { define, h, hx } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { jobHref, pageHref } from '../lib/runner'
import { card, empty, errorNotice, glyph, link, loading, notice } from '../ui/build'
import { dateTime, duration } from '../ui/format'

/** The `id` query parameter, or null for the list (an empty `?id=` too). */
export function jobIdFromUrl(search: string = window.location.search): string | null {
  const id = new URLSearchParams(search).get('id')
  return id === '' ? null : id
}

function params(j: Job): string {
  return Object.entries(j.params)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(' ')
}

/** The command's glyph painted, its name spoken. */
function commandGlyph(command: Job['command']): HTMLSpanElement {
  return glyph(COMMAND_ICON[command], commandLabel(command), 'job-cmd')
}

/** One row, plus its duration cell so ticks can refresh just that. */
function row(j: Job): { tr: HTMLTableRowElement; took: HTMLTableCellElement } {
  const args = params(j)
  // Param values are content (ids, minutes); their keys are spoken only.
  const values = Object.values(j.params).map(String).join(' ')
  const took = h('td', { class: 'num mono' })
  const summary = j.summary ?? j.progress?.label ?? ''
  const tr = h(
    'tr',
    {},
    h(
      'td',
      {},
      h('a', { href: jobHref(j.id) }, commandGlyph(j.command)),
      args ? h('span', { class: 'muted mono' }, h('span', { 'aria-hidden': 'true' }, ` ${values}`), h('span', { class: 'sr-only' }, ` ${args}`)) : null,
      // The server's summary sentence is spoken only; the state badge paints the outcome.
      summary ? h('span', { class: 'sr-only' }, ` ${summary}`) : null,
    ),
    h('td', {}, stateBadge(j.state)),
    h('td', { class: 'muted' }, dateTime(j.created_at)),
    took,
  )
  return { tr, took }
}

function pageHead(title: HTMLHeadingElement, sub: HTMLParagraphElement, actions: HTMLElement | null): HTMLElement {
  return h('header', { class: 'page-head' }, h('div', {}, title, sub), actions ? h('div', { class: 'page-actions' }, actions) : null)
}

/** `/jobs/`: the last 50 jobs. The table is built once; ticks swap the rows. */
export class JobListElement extends LiveElement {
  private status = h('div', { class: 'contents' })
  private body = h('tbody')
  private table = h('div')
  private shownKey = ''
  private took: { job: Job; td: HTMLTableCellElement }[] = []

  protected override setup(): void {
    this.status = h('div', { class: 'contents' })
    this.body = h('tbody')
    this.shownKey = ''
    this.took = []
    this.table = h(
      'div',
      { class: 'tbl', tabindex: 0, role: 'region', 'aria-label': 'Job history' },
      h(
        'table',
        {},
        h(
          'thead',
          {},
          h(
            'tr',
            {},
            h('th', { scope: 'col' }, glyph('⌨️', 'Command')),
            h('th', { scope: 'col' }, glyph('🚦', 'State')),
            h('th', { scope: 'col' }, glyph('🕐', 'Started')),
            h('th', { scope: 'col', class: 'num' }, glyph('⏱️', 'Took')),
          ),
        ),
        this.body,
      ),
    )
    const title = h('h1', { class: 'sr-only' }, 'Jobs')
    const sub = h('p', { class: 'sr-only' }, 'The last 50 jobs. They keep running if you close the page.')
    this.replaceChildren(pageHead(title, sub, null), card(null, [this.status, this.table]))
    this.watch(q.jobs)
    this.tick(1000)
  }

  protected update(): void {
    const { data, error } = q.jobs.state
    // Rows are rebuilt only when a poll brings a change, so a focused or
    // half-clicked job link survives the 1 s tick; ticks touch durations only.
    const key = JSON.stringify([data ?? null, error ? explain(error) : null])
    if (key !== this.shownKey) {
      this.shownKey = key
      this.status.replaceChildren(
        ...(error ? [errorNotice(error)] : []),
        ...(!data && !error ? [loading('jobs')] : []),
        ...(data?.length === 0 ? [empty('No jobs yet. Press Ctrl K to run a command.')] : []),
      )
      const rows = (data ?? []).map((job) => ({ job, ...row(job) }))
      this.table.hidden = rows.length === 0
      this.body.replaceChildren(...rows.map((r) => r.tr))
      this.took = rows.map((r) => ({ job: r.job, td: r.took }))
    }
    const now = Date.now()
    for (const { job, td } of this.took) td.textContent = duration(job.started_at, job.ended_at, now)
  }
}

function notFound(id: string, error: ApiFailure): HTMLDivElement {
  // ❓ + the id painted; the explanation and the server's message are spoken.
  const el = notice(
    'warning',
    null,
    h('p', { class: 'm0' }, h('span', { 'aria-hidden': 'true' }, '❓ '), h('span', { class: 'mono' }, id)),
    h('p', { class: 'm0' }, link(pageHref('/jobs'), glyph('📋', 'See all jobs'), '')),
  )
  el.dataset.code = 'not_found'
  el.setAttribute('aria-label', `Job not found. There is no job ${id}. It may have been pruned: the history keeps the last 50.${error.message ? ` ${error.message}` : ''}`)
  return el
}

/** `/jobs/?id=…`: one job. `<job-progress>` is mounted once and owns itself. */
export class JobDetailElement extends LiveElement {
  private heading = h('h1')
  private sub = h('p')
  private status = h('div')
  private mounted = false
  /** Set in setup(), which always runs before update(). */
  private unwatch!: () => void

  get jobId(): string {
    return this.getAttribute('job-id') ?? ''
  }

  protected override setup(): void {
    this.heading = h('h1', {}, 'Job')
    this.sub = h('p', { class: 'sub' })
    this.status = h('div', { class: 'contents' })
    this.mounted = false
    this.replaceChildren(pageHead(this.heading, this.sub, link(pageHref('/jobs'), glyph('📋', 'All jobs'), 'btn btn-ghost')), this.status)
    // Subscribed by hand, not via watch(): an unknown id stops polling.
    let live = true
    const off = q.job(this.jobId).subscribe(() => {
      this.update()
    })
    this.unwatch = () => {
      if (live) off()
      live = false
    }
    this.onCleanup(this.unwatch)
  }

  protected update(): void {
    const id = this.jobId
    const { data, error, loading: waiting } = q.job(id).state
    const missing = !data && error instanceof ApiFailure && error.code === 'not_found' ? error : null
    // Heading: the command's glyph (❓ when the id is unknown, ⚙️ while loading), name spoken.
    this.heading.replaceChildren(data ? commandGlyph(data.command) : missing ? glyph('❓', 'Job not found') : glyph('⚙️', 'Job'))
    this.sub.replaceChildren(
      h('span', { class: 'sr-only' }, 'Job '),
      h('span', { class: 'mono' }, id),
      data ? h('span', {}, h('span', { 'aria-hidden': 'true' }, ' · 🕐 '), h('span', { class: 'sr-only' }, ' · created '), dateTime(data.created_at)) : '',
    )
    this.status.replaceChildren(
      ...(missing ? [notFound(id, missing)] : error ? [errorNotice(error)] : waiting ? [loading('job')] : []),
    )
    if (missing) this.unwatch()
    // An unknown id never gets a live view: it would open an SSE stream for
    // nothing and sit at "Queued" forever, which reads as a real job.
    if (!this.mounted && !waiting && !missing) {
      this.mounted = true
      this.append(card(null, hx('job-progress', { 'job-id': id })))
    }
  }
}

/** Picks list or detail from `?id=` once, at connect. */
export class JobsPageElement extends HTMLElement {
  connectedCallback(): void {
    const id = jobIdFromUrl()
    this.replaceChildren(id === null ? hx('job-list') : hx('job-detail', { 'job-id': id }))
  }
}

define('job-list', JobListElement)
define('job-detail', JobDetailElement)
define('jobs-page', JobsPageElement)
