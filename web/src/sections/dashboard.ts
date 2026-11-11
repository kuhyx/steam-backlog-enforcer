// Dashboard sections (was screens/Dashboard.tsx): what the enforcer is doing
// right now, at a glance. Textgate: glyphs and numbers are painted, every
// sentence is spoken only (sr-only), game names stay visible as content.

import type { FastInstallRun, StatusPayload } from '../api/contract'
import { q } from '../api/queries'
import { COMMAND_ICON, commandLabel } from '../commands/catalog'
import '../commands/commandButton'
import { fmtDuration, fmtRemaining } from '../format'
import { progressBar, stateBadge, type BarTone } from '../jobs/progress'
import { define, h, hx } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { jobHref } from '../lib/runner'
import { card, empty, errorNotice, facts, glyph, link, loading } from '../ui/build'
import { ago } from '../ui/format'
import { said } from './spoken'

/** "5 min ago" painted as 🕓 5 min (the word "ago" spoken only). */
export function since(iso: string | null): HTMLSpanElement {
  const spoken = ago(iso)
  const short = spoken === 'just now' ? '<1 min' : spoken.replace(/ ago$/, '')
  return said(spoken, '🕓 ', short)
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
    this.replaceChildren(h('span', { class: 'text-danger' }, said(`${left} left`, '⏳ ', left)))
  }
}

function statusFacts(s: StatusPayload): HTMLDListElement {
  return facts([
    [
      glyph('💾', 'Installed'),
      s.assigned_game_installed ? glyph('✅', 'Yes') : h('span', { class: 'text-warning' }, glyph('⚠️', 'No — install it from Library')),
    ],
    [glyph('🏆', 'Games finished'), s.finished_count],
    [glyph('🛒', 'Store'), s.store_blocked ? glyph('🔒', 'Blocked') : h('span', { class: 'text-warning' }, glyph('🔓', 'Unblocked'))],
    [glyph('🗂️', 'Installed games'), s.installed_count],
    [glyph('⛔', 'Total block'), s.total_block.active ? hx('block-countdown') : glyph('➖', 'Off')],
    [
      glyph('📌', 'Manual picks'),
      s.manual_picks.length ? s.manual_picks.map((p) => `${p.name} (${p.age_days} d)`).join(', ') : glyph('➖', 'None'),
    ],
  ])
}

export class DashboardStatusElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const { data, error } = q.status.state
    const icon = '🎯'
    if (error) {
      this.replaceChildren(card('Assignment', errorNotice(error), { icon }))
    } else if (!data) {
      this.replaceChildren(card('Assignment', loading('status'), { icon }))
    } else {
      const game = data.current_game_name ?? glyph('📭', 'Nothing assigned')
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
  if (blocked) return h('p', { class: 'field-help' }, glyph('⛔', 'Blocked for today.'))
  if (!label) return h('p', { class: 'field-help' }, said('Now: nothing billing', '⏸️'))
  return h('p', { class: 'field-help' }, said(`Now: ${label}`, '▶️ ', label))
}

export class BudgetGlanceElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.budget)
  }

  protected update(): void {
    const { data, error } = q.budget.state
    const icon = '⏱️'
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
          h(
            'p',
            { class: 'hero-num' },
            `${fmtDuration(t.seconds_remaining)} `,
            h('span', { class: 'muted' }, said(`left of ${fmtDuration(t.budget_seconds)}`, `/ ${fmtDuration(t.budget_seconds)}`)),
          ),
          progressBar(t.fraction_used, 'Budget used', budgetTone(t.blocked, t.fraction_used)),
          billingLine(t.blocked, data.session.billing_label),
        ]
      : h('p', { class: 'text-danger' }, data.error ?? glyph('⚠️', 'Budget state unavailable.'))
    this.replaceChildren(card('Gaming today', body, { icon, aside: link('/gaming/', glyph('➡️', 'Details')) }))
  }
}

function fastInstallRow(r: FastInstallRun): HTMLDivElement {
  if (r.error) {
    // The daemon has no job to report to: a failure stays here until Steam finishes.
    // The error is the daemon's own message (content), the framing is spoken.
    return h(
      'div',
      {},
      h('p', { class: 'text-danger' }, said(`Fast install of ${r.name} failed: ${r.error}`, '⛔ ', r.name, ': ', r.error)),
      h('p', { class: 'field-help' }, glyph('↪️', "Steam's own download took over.")),
    )
  }
  const pct = r.percent === null ? null : Math.floor(r.percent)
  const where = pct === null ? r.phase : `${pct}% (${r.phase})`
  return h(
    'div',
    {},
    h('p', {}, said(`Fast-installing ${r.name} — ${where}`, '⚡ ', r.name, pct === null ? '' : ` ${pct}%`)),
    progressBar(pct === null ? null : pct / 100, `${r.name} download`),
    h('p', { class: 'field-help' }, said(`${fmtDuration(r.elapsed_seconds)} elapsed`, '⏳ ', fmtDuration(r.elapsed_seconds))),
  )
}

/** Daemon-started fast installs; a web job shows its own in the job view. */
export class FastInstallsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.daemon)
  }

  protected update(): void {
    const runs = q.daemon.state.data?.fast_installs ?? []
    this.replaceChildren(...(runs.length ? [card('Fast install', runs.map(fastInstallRow), { icon: '⚡' })] : []))
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
                  glyph(COMMAND_ICON[j.command], commandLabel(j.command)),
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
        { icon: '⚙️', aside: link('/jobs/', glyph('➡️', 'All jobs')) },
      ),
    )
  }
}

define('block-countdown', BlockCountdownElement)
define('dashboard-status', DashboardStatusElement)
define('budget-glance', BudgetGlanceElement)
define('fast-installs', FastInstallsElement)
define('recent-jobs', RecentJobsElement)
