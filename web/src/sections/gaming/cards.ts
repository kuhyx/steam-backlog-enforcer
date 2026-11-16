// The four budget panel sections (were BudgetTodayCard, BudgetLiveCard,
// BudgetHistoryChart and BudgetRulesCard.tsx) as pure DOM builders.
// Textgate: glyphs, numbers and game names are painted; every sentence and
// label is spoken only (`said`/`glyph`), and the meter/verdict colours stay.

import { OTHER_KEY, UNATTRIBUTED_KEY, seriesClass } from '../../budgetSeries'
import { fmtAgo, fmtDuration } from '../../format'
import { budgetHistorySvg } from '../../lib/charts/budgetHistory'
import { iconInline } from '../../icons/render'
import type { IconId } from '../../icons/registry'
import { h } from '../../lib/dom'
import type { BudgetHistoryDay, BudgetLegendEntry, BudgetRules, BudgetSession, BudgetToday } from '../../types'
import { glyph } from '../../ui/build'
import { said } from '../spoken'

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

/** A series name: game names are content; the sentinels and the "(launcher)" tag are glyphs. */
export function seriesLabel(key: string, label: string): HTMLElement {
  if (key === OTHER_KEY) return glyph('gaming.series.other', label)
  if (key === UNATTRIBUTED_KEY) return glyph('gaming.series.unattributed', label)
  if (key.startsWith('launcher:')) return said(label, iconInline('gaming.launcher'), ' ', label.replace(/\s*\(launcher\)$/, ''))
  return h('span', {}, label)
}

/** "5m ago" painted as the as-of icon and 5m. */
function asOf(iso: string): HTMLElement {
  const ago = fmtAgo(iso)
  const short = ago === 'unknown' ? '?' : ago === 'just now' ? '<10s' : ago.replace(/ ago$/, '')
  return said(`as of ${ago}`, iconInline('dash.ago'), ' ', short)
}

function warningLine(today: BudgetToday, maskedCount: number): HTMLElement {
  if (today.blocked) {
    // Read the live mount count rather than inferring it from `blocked`: the
    // total-block branch releases every mount while leaving `blocked_at` set,
    // so the two can genuinely disagree, and a badge claiming a mask that is
    // not there is the one thing this panel must never do.
    return h(
      'span',
      { class: 'budget-badge budget-badge--blocked' },
      maskedCount > 0
        ? glyph('gaming.cutoff.masked', 'Cutoff engaged — launchers are masked')
        : glyph('gaming.cutoff.unmasked', 'Cutoff engaged — launchers are not currently masked'),
    )
  }
  const next = today.next_warning_seconds
  return next === null
    ? glyph('gaming.warn.none', 'No further warnings today.')
    : said(`Next warning at ${fmtDuration(next)} remaining.`, iconInline('gaming.warning'), ' ', fmtDuration(next))
}

function usageLine(t: BudgetToday): HTMLElement {
  const used = `${fmtDuration(t.seconds_used)} / ${fmtDuration(t.budget_seconds)} · ${Math.round(t.fraction_used * 100)}%`
  const spoken =
    `${fmtDuration(t.seconds_used)} of ${fmtDuration(t.budget_seconds)} used · ` +
    `${Math.round(t.fraction_used * 100)}% · gaming day ${t.gaming_day} (starts ${t.day_starts_at})`
  return said(
    spoken,
    used,
    ' · ',
    iconInline('gaming.day'),
    ' ',
    t.gaming_day,
    ' · ',
    iconInline('gaming.day_start'),
    ' ',
    t.day_starts_at.replace(/\s*local$/, ''),
  )
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
    h('h2', {}, glyph('gaming.today', 'Today')),
    h('p', { class: 'budget-hero' }, h('strong', {}, fmtDuration(today.seconds_remaining)), h('span', { class: 'sr-only' }, ' left')),
    h('div', { class: `budget-meter budget-meter--${meterState(today)}` }, fill),
    h('p', { class: 'hint' }, usageLine(today)),
    h('p', { class: 'hint' }, warningLine(today, maskedCount)),
    today.games.length > 0
      ? [
          h('h3', { class: 'budget-subhead' }, glyph('gaming.by_game', 'Today by game')),
          h(
            'ul',
            { class: 'budget-games' },
            today.games.map((game, i) =>
              h(
                'li',
                {},
                h('span', { class: `swatch ${seriesClass(game.key, indexFor.get(game.key) ?? i)}`, 'aria-hidden': 'true' }),
                h('span', { class: 'budget-game-name' }, seriesLabel(game.key, game.label)),
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
  return h(
    'section',
    { class: 'budget-today' },
    h('h2', {}, glyph('gaming.today', 'Today')),
    // The server's own error is shown as is; the fallback is a glyph.
    h('p', { class: 'error' }, error ?? glyph('state.warn', 'Budget state unavailable.')),
  )
}

const VERDICT = new Map<string, readonly [IconId, string]>([
  ['engaged', ['dash.billing', 'Billing — you are playing']],
  ['not_applicable', ['dash.not-billing', 'Not billing — no game running']],
])

export function liveCard(session: BudgetSession): HTMLElement {
  const title = h('h2', {}, glyph('gaming.right_now', 'Right now'))
  if (!session.available) {
    return h('section', { class: 'budget-live' }, title, h('p', { class: 'hint' }, glyph('state.empty', 'No verdict has been logged yet.')))
  }
  const [icon, verdict] = VERDICT.get(session.state) ?? (['state.unknown', session.state] as const)
  return h(
    'section',
    { class: 'budget-live' },
    title,
    h('p', {}, h('span', { class: `budget-verdict budget-verdict--${session.state}` }, glyph(icon, verdict))),
    session.qualifying_count > 0
      ? h(
          'p',
          { class: 'hint' },
          session.game_name ? [said('Assigned game ', iconInline('assigned.game'), ' '), h('strong', {}, session.game_name), ' · '] : null,
          said(`${session.qualifying_count} qualifying processes`, iconInline('gaming.qualifying'), ' ', session.qualifying_count),
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
          session.state === 'engaged'
            ? said('Billing to ', iconInline('gaming.billing_to'), ' ')
            : said('Last billed to ', iconInline('gaming.billed_last'), ' '),
          h('strong', {}, session.billing_label),
        )
      : null,
    // The daemon logs on change or a 5-minute heartbeat, so this reading can
    // legitimately be minutes old. Saying so beats implying "now".
    h('p', { class: 'hint' }, asOf(session.observed_at)),
  )
}

export function historyCard(days: readonly BudgetHistoryDay[], legend: readonly BudgetLegendEntry[], budgetSeconds: number): HTMLElement {
  const title = h('h2', {}, glyph('gaming.history', 'Last 14 days'))
  if (days.length === 0) {
    return h(
      'div',
      { class: 'chart' },
      title,
      h('p', { class: 'hint' }, glyph('state.empty', 'No budget history recorded yet — a bar appears for each gaming day from now on.')),
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
      legend.map((entry, i) =>
        h('li', {}, h('span', { class: `swatch ${seriesClass(entry.key, i)}`, 'aria-hidden': 'true' }), seriesLabel(entry.key, entry.label)),
      ),
    ),
    h(
      'p',
      { class: 'sr-only' },
      "Billed gaming time per day, split by game. The dashed line is the daily budget; today's bar can still move.",
    ),
  )
}

const onOff = (value: boolean, on: string, off: string) => (value ? glyph('state.yes', on) : glyph('state.off', off))

export function rulesCard(rules: BudgetRules): HTMLElement {
  const row = (icon: IconId, term: string, value: Node | string) => [h('dt', {}, glyph(icon, term)), h('dd', {}, value)]
  const warn = rules.warn_at.map((s) => fmtDuration(s)).join(', ')
  return h(
    'section',
    { class: 'budget-rules' },
    h('h2', {}, glyph('gaming.rules', 'Rules in effect')),
    h(
      'dl',
      { class: 'budget-rules-list' },
      row('gaming.budget', 'Daily budget', fmtDuration(rules.budget_seconds)),
      row('gaming.enforcement', 'Enforcement', onOff(rules.enforcement, 'on', 'off')),
      row('gaming.launcher', 'Counts launchers', onOff(rules.counts_launchers, 'yes', 'no')),
      row('gaming.warning', 'Warnings at', said(`${warn} remaining`, warn)),
      rules.demo ? row('gaming.mode', 'Mode', glyph('gaming.demo', 'demo (short budget, separate state)')) : null,
      rules.masked_launchers.length > 0 ? row('gaming.masked', 'Masked now', rules.masked_launchers.join(', ')) : null,
    ),
  )
}
