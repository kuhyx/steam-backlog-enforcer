// Dashboard sections (was screens/Dashboard.tsx): what the enforcer is doing
// right now, at a glance.

import type { FastInstallRun, StatusPayload } from '../api/contract'
import { q } from '../api/queries'
import { commandLabel } from '../commands/catalog'
import '../commands/commandButton'
import { fmtDuration, fmtRemaining } from '../format'
import { progressBar, stateBadge, type BarTone } from '../jobs/progress'
import { define, h, hx } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { jobHref } from '../lib/runner'
import { card, empty, errorNotice, facts, link, loading } from '../ui/build'
import { ago } from '../ui/format'

/** Seconds left on the total block: from `until` when known, else the
 *  server's `days_remaining` (rounded to 0.1 d). */
export function blockSecondsLeft(block: StatusPayload['total_block'], now: number = Date.now()): number {
  return block.until ? (Date.parse(block.until) - now) / 1000 : block.days_remaining * 86_400
}

/** The total-block countdown. Ticks on its own every second so the status
 *  card (and its "Check now" button) is rebuilt only when status changes. */
export class BlockCountdownElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
    this.tick(1000)
  }

  protected update(): void {
    const block = q.status.state.data?.total_block
    this.replaceChildren(...(block ? [h('span', { class: 'text-danger' }, `${fmtRemaining(blockSecondsLeft(block))} left`)] : []))
  }
}

function statusFacts(s: StatusPayload): HTMLDListElement {
  return facts([
    ['Installed', s.assigned_game_installed ? 'Yes' : h('span', { class: 'text-warning' }, 'No — install it from Library')],
    ['Games finished', s.finished_count],
    ['Store', s.store_blocked ? 'Blocked' : h('span', { class: 'text-warning' }, 'Unblocked')],
    ['Installed games', s.installed_count],
    ['Total block', s.total_block.active ? hx('block-countdown') : 'Off'],
    ['Manual picks', s.manual_picks.length ? s.manual_picks.map((p) => `${p.name} (${p.age_days} d)`).join(', ') : 'None'],
  ])
}

export class DashboardStatusElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const { data, error } = q.status.state
    if (error) {
      this.replaceChildren(card('Assignment', errorNotice(error)))
    } else if (!data) {
      this.replaceChildren(card('Assignment', loading('status')))
    } else {
      this.replaceChildren(
        card('Assignment', [h('p', { class: 'hero-game' }, data.current_game_name ?? 'Nothing assigned'), statusFacts(data)], {
          // Its own element, so it follows the command catalog by itself.
          aside: hx('command-button', { name: 'check', label: 'Check now' }),
        }),
      )
    }
  }
}

function budgetTone(blocked: boolean, used: number): BarTone {
  if (blocked) return 'danger'
  return used > 0.8 ? 'warning' : 'accent'
}

export class BudgetGlanceElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.budget)
  }

  protected update(): void {
    const { data, error } = q.budget.state
    if (error) {
      this.replaceChildren(card('Gaming today', errorNotice(error)))
      return
    }
    if (!data) {
      this.replaceChildren(card('Gaming today', loading('budget')))
      return
    }
    const t = data.today
    const body = t
      ? [
          h(
            'p',
            { class: 'hero-num' },
            `${fmtDuration(t.seconds_remaining)} `,
            h('span', { class: 'muted' }, `left of ${fmtDuration(t.budget_seconds)}`),
          ),
          progressBar(t.fraction_used, 'Budget used', budgetTone(t.blocked, t.fraction_used)),
          h('p', { class: 'field-help' }, t.blocked ? 'Blocked for today.' : `Now: ${data.session.billing_label || 'nothing billing'}`),
        ]
      : h('p', { class: 'text-danger' }, data.error ?? 'Budget state unavailable.')
    this.replaceChildren(card('Gaming today', body, { aside: link('/gaming/', 'Details') }))
  }
}

function fastInstallLine(r: FastInstallRun): string {
  const where = r.percent === null ? r.phase : `${Math.floor(r.percent)}% (${r.phase})`
  return `Fast-installing ${r.name} — ${where}`
}

function fastInstallRow(r: FastInstallRun): HTMLDivElement {
  if (r.error) {
    // The daemon has no job to report to: a failure stays here until Steam finishes.
    return h(
      'div',
      {},
      h('p', { class: 'text-danger' }, `Fast install of ${r.name} failed: ${r.error}`),
      h('p', { class: 'field-help' }, "Steam's own download took over."),
    )
  }
  return h(
    'div',
    {},
    h('p', {}, fastInstallLine(r)),
    progressBar(r.percent === null ? null : Math.floor(r.percent) / 100, `${r.name} download`),
    h('p', { class: 'field-help' }, `${fmtDuration(r.elapsed_seconds)} elapsed`),
  )
}

/** Daemon-started fast installs; a web job shows its own in the job view. */
export class FastInstallsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.daemon)
  }

  protected update(): void {
    const runs = q.daemon.state.data?.fast_installs ?? []
    this.replaceChildren(...(runs.length ? [card('Fast install', runs.map(fastInstallRow))] : []))
  }
}

export class RecentJobsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.jobs)
  }

  protected update(): void {
    const { data, error } = q.jobs.state
    this.replaceChildren(
      card(
        'Recent jobs',
        [
          error ? errorNotice(error) : null,
          data?.length === 0 ? empty('No jobs yet. Run one from the actions or press Ctrl K.') : null,
          h(
            'ul',
            { class: 'rows' },
            (data ?? []).slice(0, 5).map((j) =>
              h(
                'li',
                {},
                h(
                  'a',
                  { href: jobHref(j.id), class: 'row-link' },
                  h('span', {}, commandLabel(j.command)),
                  h('span', { class: 'muted grow ellipsis' }, j.summary ?? j.progress?.label ?? ''),
                  h('span', { class: 'muted' }, ago(j.created_at)),
                  stateBadge(j.state),
                ),
              ),
            ),
          ),
        ],
        { aside: link('/jobs/', 'All jobs') },
      ),
    )
  }
}

define('block-countdown', BlockCountdownElement)
define('dashboard-status', DashboardStatusElement)
define('budget-glance', BudgetGlanceElement)
define('fast-installs', FastInstallsElement)
define('recent-jobs', RecentJobsElement)
