// Dashboard sections (was screens/Dashboard.tsx): what the enforcer is doing
// right now, at a glance. Textgate: glyphs and numbers are painted, every
// sentence is spoken only (sr-only), game names stay visible as content.

import type { FastInstallRun, StatusPayload } from '../api/contract'
import { q } from '../api/queries'
import { commandIcon, commandLabel } from '../commands/catalog'
import '../commands/commandButton'
import { fmtDuration, fmtRemaining } from '../format'
import { progressBar, stateBadge, type BarTone } from '../jobs/progress'
import { iconInline } from '../icons/render'
import { define, h, hx } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { jobHref } from '../lib/runner'
import { card, empty, errorNotice, facts, glyph, link, loading } from '../ui/build'
import { ago } from '../ui/format'
import { said } from './spoken'

/** "5 min ago" painted as a clock icon and 5 min (the word "ago" spoken only). */
export function since(iso: string | null): HTMLSpanElement {
  const spoken = ago(iso)
  const short = spoken === 'just now' ? '<1 min' : spoken.replace(/ ago$/, '')
  return said(spoken, iconInline('dash.ago'), ' ', short)
}

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
    if (!block) {
      this.replaceChildren()
      return
    }
    const left = fmtRemaining(blockSecondsLeft(block))
    this.replaceChildren(h('span', { class: 'text-danger' }, said(`${left} left`, iconInline('dash.block-left'), ' ', left)))
  }
}

function statusFacts(s: StatusPayload): HTMLDListElement {
  return facts([
    [
      glyph('dash.installed', 'Installed'),
      s.assigned_game_installed ? glyph('state.yes', 'Yes') : h('span', { class: 'text-warning' }, glyph('state.warn', 'No — install it from Library')),
    ],
    [glyph('dash.finished', 'Games finished'), s.finished_count],
    [
      glyph('dash.store', 'Store'),
      s.store_blocked ? glyph('dash.store-blocked', 'Blocked') : h('span', { class: 'text-warning' }, glyph('dash.store-open', 'Unblocked')),
    ],
    [glyph('dash.games', 'Installed games'), s.installed_count],
    [glyph('dash.total-block', 'Total block'), s.total_block.active ? hx('block-countdown') : glyph('state.off', 'Off')],
    [
      glyph('picks.manual', 'Manual picks'),
      s.manual_picks.length ? s.manual_picks.map((p) => `${p.name} (${p.age_days} d)`).join(', ') : glyph('state.off', 'None'),
    ],
  ])
}

export class DashboardStatusElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const { data, error } = q.status.state
    const icon = 'assigned.game'
    if (error) {
      this.replaceChildren(card('Assignment', errorNotice(error), { icon }))
    } else if (!data) {
      this.replaceChildren(card('Assignment', loading('status'), { icon }))
    } else {
      const game = data.current_game_name ?? glyph('state.empty', 'Nothing assigned')
      this.replaceChildren(
        card('Assignment', [h('p', { class: 'hero-game' }, game), statusFacts(data)], {
          icon,
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

function billingLine(blocked: boolean, label: string): HTMLParagraphElement {
  if (blocked) return h('p', { class: 'field-help' }, glyph('dash.blocked-today', 'Blocked for today.'))
  if (!label) return h('p', { class: 'field-help' }, said('Now: nothing billing', iconInline('dash.not-billing')))
  return h('p', { class: 'field-help' }, said(`Now: ${label}`, iconInline('dash.billing'), ' ', label))
}

export class BudgetGlanceElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.budget)
  }

  protected update(): void {
    const { data, error } = q.budget.state
    const icon = 'dash.budget'
    if (error) {
      this.replaceChildren(card('Gaming today', errorNotice(error), { icon }))
      return
    }
    if (!data) {
      this.replaceChildren(card('Gaming today', loading('budget'), { icon }))
      return
    }
    const t = data.today
    const body = t
      ? [
          // From 2026-11-16 there is no budget: the mark replaces the countdown and the bar.
          t.unlimited || t.fraction_used === null || t.budget_seconds === null || t.seconds_remaining === null
            ? h('p', { class: 'hero-num' }, glyph('filter.no-cap', 'No gaming limit'))
            : [
                h(
                  'p',
                  { class: 'hero-num' },
                  `${fmtDuration(t.seconds_remaining)} `,
                  h('span', { class: 'muted' }, said(`left of ${fmtDuration(t.budget_seconds)}`, `/ ${fmtDuration(t.budget_seconds)}`)),
                ),
                progressBar(t.fraction_used, 'Budget used', budgetTone(t.blocked, t.fraction_used)),
              ],
          billingLine(t.blocked, data.session.billing_label),
        ]
      : h('p', { class: 'text-danger' }, data.error ?? glyph('state.warn', 'Budget state unavailable.'))
    this.replaceChildren(card('Gaming today', body, { icon, aside: link('/gaming/', glyph('action.open', 'Details')) }))
  }
}

function fastInstallRow(r: FastInstallRun): HTMLDivElement {
  if (r.error) {
    // The daemon has no job to report to: a failure stays here until Steam finishes.
    // The error is the daemon's own message (content), the framing is spoken.
    return h(
      'div',
      {},
      h('p', { class: 'text-danger' }, said(`Fast install of ${r.name} failed: ${r.error}`, iconInline('dash.fast-failed'), ' ', r.name, ': ', r.error)),
      h('p', { class: 'field-help' }, glyph('dash.steam-took-over', "Steam's own download took over.")),
    )
  }
  const pct = r.percent === null ? null : Math.floor(r.percent)
  const where = pct === null ? r.phase : `${pct}% (${r.phase})`
  return h(
    'div',
    {},
    h('p', {}, said(`Fast-installing ${r.name} — ${where}`, iconInline('dash.fast-install'), ' ', r.name, pct === null ? '' : ` ${pct}%`)),
    progressBar(pct === null ? null : pct / 100, `${r.name} download`),
    h('p', { class: 'field-help' }, said(`${fmtDuration(r.elapsed_seconds)} elapsed`, iconInline('dash.elapsed'), ' ', fmtDuration(r.elapsed_seconds))),
  )
}

/** Daemon-started fast installs; a web job shows its own in the job view. */
export class FastInstallsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.daemon)
  }

  protected update(): void {
    const runs = q.daemon.state.data?.fast_installs ?? []
    this.replaceChildren(...(runs.length ? [card('Fast install', runs.map(fastInstallRow), { icon: 'dash.fast-install' })] : []))
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
                  glyph(commandIcon(j.command), commandLabel(j.command)),
                  // The job's summary is a server sentence: spoken here, shown in the job view.
                  h('span', { class: 'sr-only' }, j.summary ?? j.progress?.label ?? ''),
                  h('span', { class: 'grow' }),
                  h('span', { class: 'muted' }, since(j.created_at)),
                  stateBadge(j.state),
                ),
              ),
            ),
          ),
        ],
        { icon: 'dash.recent-jobs', aside: link('/jobs/', glyph('action.open', 'All jobs')) },
      ),
    )
  }
}

define('block-countdown', BlockCountdownElement)
define('dashboard-status', DashboardStatusElement)
define('budget-glance', BudgetGlanceElement)
define('fast-installs', FastInstallsElement)
define('recent-jobs', RecentJobsElement)
