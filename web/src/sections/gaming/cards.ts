// The four budget panel sections (were BudgetTodayCard, BudgetLiveCard,
// BudgetHistoryChart and BudgetRulesCard.tsx) as pure DOM builders.

import { seriesClass } from '../../budgetSeries'
import { fmtAgo, fmtDuration } from '../../format'
import { budgetHistorySvg } from '../../lib/charts/budgetHistory'
import { h } from '../../lib/dom'
import type { BudgetHistoryDay, BudgetLegendEntry, BudgetRules, BudgetSession, BudgetToday } from '../../types'

/** Which colour the meter takes: normal, into the warning band, or spent.
 *
 * Keyed on warnings already fired rather than on `next_warning_seconds`: that
 * field is by construction always *below* the remaining time, so comparing the
 * two could never turn the meter amber. "The enforcer has warned you" is also
 * the thing the colour is actually trying to say.
 */
function meterState(today: BudgetToday): string {
  if (today.blocked) return 'blocked'
  return today.warned_seconds.length > 0 ? 'warn' : 'ok'
}

function warningLine(today: BudgetToday, maskedCount: number): HTMLElement | string {
  if (today.blocked) {
    // Read the live mount count rather than inferring it from `blocked`: the
    // total-block branch releases every mount while leaving `blocked_at` set,
    // so the two can genuinely disagree, and a badge claiming a mask that is
    // not there is the one thing this panel must never do.
    return h(
      'span',
      { class: 'budget-badge budget-badge--blocked' },
      maskedCount > 0 ? 'Cutoff engaged — launchers are masked' : 'Cutoff engaged — launchers are not currently masked',
    )
  }
  return today.next_warning_seconds === null
    ? 'No further warnings today.'
    : `Next warning at ${fmtDuration(today.next_warning_seconds)} remaining.`
}

export function todayCard(today: BudgetToday, legend: readonly BudgetLegendEntry[], maskedCount: number): HTMLElement {
  // Colour by the chart's legend position so a game reads the same in both
  // places; today can hold games the capped 14-day legend left out, and those
  // fall back to their own row order.
  const indexFor = new Map(legend.map((e, i) => [e.key, i]))
  const fill = h('div', { class: 'budget-meter-fill' })
  fill.style.width = `${(today.fraction_used * 100).toFixed(1)}%`
  return h(
    'section',
    { class: 'budget-today' },
    h('h2', {}, 'Today'),
    h('p', { class: 'budget-hero' }, h('strong', {}, fmtDuration(today.seconds_remaining)), ' left'),
    h('div', { class: `budget-meter budget-meter--${meterState(today)}` }, fill),
    h(
      'p',
      { class: 'hint' },
      `${fmtDuration(today.seconds_used)} of ${fmtDuration(today.budget_seconds)} used · ` +
        `${Math.round(today.fraction_used * 100)}% · gaming day ${today.gaming_day} (starts ${today.day_starts_at})`,
    ),
    h('p', { class: 'hint' }, warningLine(today, maskedCount)),
    today.games.length > 0
      ? [
          h('h3', { class: 'budget-subhead' }, 'Today by game'),
          h(
            'ul',
            { class: 'budget-games' },
            today.games.map((game, i) =>
              h(
                'li',
                {},
                h('span', { class: `swatch ${seriesClass(game.key, indexFor.get(game.key) ?? i)}`, 'aria-hidden': 'true' }),
                h('span', { class: 'budget-game-name' }, game.label),
                h('span', { class: 'budget-game-time' }, fmtDuration(game.seconds)),
                h('span', { class: 'budget-game-share' }, `${Math.round(game.fraction * 100)}%`),
              ),
            ),
          ),
        ]
      : null,
  )
}

/** Shown in place of `todayCard` when the state file cannot be read. */
export function todayUnavailable(error: string | null): HTMLElement {
  return h('section', { class: 'budget-today' }, h('h2', {}, 'Today'), h('p', { class: 'error' }, error ?? 'Budget state unavailable.'))
}

const VERDICT_LABELS = new Map([
  ['engaged', 'Billing — you are playing'],
  ['not_applicable', 'Not billing — no game running'],
])

export function liveCard(session: BudgetSession): HTMLElement {
  const title = h('h2', {}, 'Right now')
  if (!session.available) {
    return h('section', { class: 'budget-live' }, title, h('p', { class: 'hint' }, 'No verdict has been logged yet.'))
  }
  return h(
    'section',
    { class: 'budget-live' },
    title,
    h(
      'p',
      {},
      h('span', { class: `budget-verdict budget-verdict--${session.state}` }, VERDICT_LABELS.get(session.state) ?? session.state),
    ),
    session.qualifying_count > 0
      ? h(
          'p',
          { class: 'hint' },
          session.game_name ? ['Assigned game ', h('strong', {}, session.game_name), ' · '] : null,
          `${session.qualifying_count} qualifying processes`,
        )
      : null,
    // The assignment above is what the enforcer told you to play; this is
    // what the budget charged. A counted non-Steam game is never the
    // assignment, so the two legitimately differ. The key is the *last* one
    // credited, so it must not claim to be live once nothing qualifies.
    session.billing_label
      ? h(
          'p',
          { class: 'hint' },
          session.state === 'engaged' ? 'Billing to ' : 'Last billed to ',
          h('strong', {}, session.billing_label),
        )
      : null,
    // The daemon logs on change or a 5-minute heartbeat, so this reading can
    // legitimately be minutes old. Saying so beats implying "now".
    h('p', { class: 'hint' }, `as of ${fmtAgo(session.observed_at)}`),
  )
}

export function historyCard(days: readonly BudgetHistoryDay[], legend: readonly BudgetLegendEntry[], budgetSeconds: number): HTMLElement {
  const title = h('h2', {}, 'Last 14 days')
  if (days.length === 0) {
    return h(
      'div',
      { class: 'chart' },
      title,
      h('p', { class: 'hint' }, 'No budget history recorded yet — a bar appears for each gaming day from now on.'),
    )
  }
  // A <template> parses the markup as HTML, which puts <svg> in the SVG namespace.
  const plot = document.createElement('template')
  plot.innerHTML = budgetHistorySvg(days, legend, budgetSeconds)
  return h(
    'div',
    { class: 'chart' },
    title,
    plot.content,
    h(
      'ul',
      { class: 'chart-legend' },
      legend.map((entry, i) => h('li', {}, h('span', { class: `swatch ${seriesClass(entry.key, i)}`, 'aria-hidden': 'true' }), entry.label)),
    ),
    h(
      'p',
      { class: 'hint' },
      "Billed gaming time per day, split by game. The dashed line is the daily budget; today's bar can still move.",
    ),
  )
}

const onOff = (value: boolean): string => (value ? 'on' : 'off')

export function rulesCard(rules: BudgetRules): HTMLElement {
  const row = (term: string, value: string) => [h('dt', {}, term), h('dd', {}, value)]
  return h(
    'section',
    { class: 'budget-rules' },
    h('h2', {}, 'Rules in effect'),
    h(
      'dl',
      { class: 'budget-rules-list' },
      row('Daily budget', fmtDuration(rules.budget_seconds)),
      row('Enforcement', onOff(rules.enforcement)),
      row('Counts launchers', rules.counts_launchers ? 'yes' : 'no'),
      row('Warnings at', `${rules.warn_at.map((s) => fmtDuration(s)).join(', ')} remaining`),
      rules.demo ? row('Mode', 'demo (short budget, separate state)') : null,
      rules.masked_launchers.length > 0 ? row('Masked now', rules.masked_launchers.join(', ')) : null,
    ),
  )
}
