// The planner's headline: games in scope, the target-date banner, one card per
// estimate basis and the player's pace vs HLTB (was SummaryCards.tsx).

import { basisTotal, etaDays, paceDays, playerEstimatedTotal, type EstimateResult } from '../../estimate'
import { fmtEta, fmtHours } from '../../format'
import { h } from '../../lib/dom'
import type { EstimateBasis, Filters, PaceVsHLTB, WebStateInfo } from '../../types'

export interface SummaryProps {
  result: EstimateResult
  filters: Filters
  state: WebStateInfo
  presets: readonly number[]
  defaultQualifying: number
  paceVsHltb: PaceVsHLTB | null
}

const CARDS: readonly { basis: EstimateBasis; title: string; blurb: string }[] = [
  { basis: 'rush', title: 'Rush', blurb: 'Typical fast completionist' },
  { basis: 'leisure', title: 'Leisure', blurb: 'Slow, comfortable 100%' },
  { basis: 'worst', title: 'Worst case', blurb: 'Max recorded time' },
  { basis: 'pace', title: 'At your pace', blurb: 'Based on games finished' },
]

const STYLE_LABELS: Record<string, string> = {
  faster_than_rush: 'Faster than rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than leisure',
  unknown: 'Unknown',
}

function targetBanner({ result, filters }: SummaryProps, now: Date): HTMLDivElement | null {
  if (!filters.targetDate) return null
  const target = new Date(filters.targetDate)
  const days = Math.max(1, Math.ceil((target.getTime() - now.getTime()) / 86400000))
  // Pace is the only basis without an hours total: it needs games per day.
  const total = basisTotal(result, filters.basis)
  const need =
    total === null ? `${(result.remainingGames / days).toFixed(2)} games/day` : `${(total / days).toFixed(1)} h/day`
  return h(
    'div',
    { class: 'target-banner' },
    'To finish ',
    h('strong', {}, result.remainingGames),
    ' games by ',
    h('strong', {}, filters.targetDate),
    ` (${days} days) on the `,
    h('strong', {}, filters.basis),
    ' model, you need ',
    h('strong', {}, need),
    '.',
  )
}

const presetRows = (presets: readonly number[], eta: (perDay: number) => number | null) =>
  h(
    'div',
    { class: 'presets' },
    presets.map((p) => h('div', { class: 'preset' }, h('span', {}, `${p} h/day`), h('span', {}, fmtEta(eta(p))))),
  )

const pair = (label: string, value: string, attrs: Record<string, string> = {}) => [
  h('span', {}, label),
  h('span', attrs, value),
]

function playerInsight({ result, paceVsHltb: pace, presets }: SummaryProps): HTMLDivElement {
  const title = h('div', { class: 'player-insight-title' }, 'Your Play Style vs HLTB')
  if (!pace || pace.calibration_count === 0) {
    return h(
      'div',
      { class: 'player-insight player-insight--empty' },
      title,
      h(
        'p',
        { class: 'player-insight-empty' },
        'No calibration data yet. Finish games (100% achievements) and re-run ',
        h('code', {}, 'stats'),
        ' to see your pace estimate.',
      ),
    )
  }
  const estimated = playerEstimatedTotal(result.rushTotal, result.leisureTotal, pace)
  return h(
    'div',
    { class: 'player-insight' },
    title,
    h(
      'div',
      { class: 'player-insight-grid' },
      pair('Calibration games', String(pace.calibration_count)),
      pace.ratio_vs_rush !== -1
        ? pair('vs Rush speed', `${pace.ratio_vs_rush.toFixed(2)}×`, {
            class: pace.ratio_vs_rush <= 1 ? 'player-insight-fast' : 'player-insight-slow',
          })
        : null,
      pace.ratio_vs_leisure !== -1 ? pair('vs Leisure speed', `${pace.ratio_vs_leisure.toFixed(2)}×`) : null,
      pace.interpolation_t !== -1
        ? pair('Interpolation t', pace.interpolation_t.toFixed(3), { title: '0 = rush speed · 1 = leisure speed' })
        : null,
      pair('Play style', STYLE_LABELS[pace.player_style] ?? pace.player_style, {
        class: `player-insight-style player-insight-style--${pace.player_style}`,
      }),
    ),
    estimated !== null
      ? h(
          'div',
          { class: 'player-insight-estimate' },
          h(
            'div',
            { class: 'player-insight-estimate-total' },
            'Estimated total at your pace: ',
            h('strong', { class: 'player-insight-estimate-hours' }, fmtHours(estimated)),
          ),
          presetRows(presets, (p) => (estimated > 0 ? Math.floor(estimated / p) : null)),
        )
      : null,
  )
}

function basisCard(props: SummaryProps, c: (typeof CARDS)[number]): HTMLDivElement {
  const { result, filters, state, presets } = props
  const isPace = c.basis === 'pace'
  const total = basisTotal(result, c.basis) ?? 0
  const pace = state.pace_games_per_day
  const eta = isPace ? paceDays(result.remainingGames, pace) : etaDays(total, filters.dailyHours)
  return h(
    'div',
    { class: filters.basis === c.basis ? 'card active' : 'card' },
    h('div', { class: 'card-title' }, c.title),
    h('div', { class: 'card-blurb' }, c.blurb),
    h('div', { class: 'card-total' }, isPace ? `${pace} games/day` : fmtHours(total)),
    h('div', { class: 'card-eta' }, isPace && !pace ? 'No start date set' : fmtEta(eta)),
    isPace ? null : presetRows(presets, (p) => etaDays(total, p)),
  )
}

export function summaryCards(props: SummaryProps, now: Date = new Date()): HTMLDivElement {
  const { result, defaultQualifying } = props
  return h(
    'div',
    { class: 'summary' },
    h(
      'div',
      { class: 'summary-head' },
      h(
        'div',
        {},
        h('span', { class: 'big' }, result.remainingGames.toLocaleString()),
        h('span', { class: 'big-label' }, 'games in scope'),
      ),
      h(
        'div',
        { class: 'parity' },
        'CLI default qualifies ',
        h('strong', {}, defaultQualifying),
        result.remainingGames === defaultQualifying ? h('span', { class: 'ok' }, ' ✓ match') : null,
      ),
    ),
    targetBanner(props, now),
    h('div', { class: 'cards' }, CARDS.map((c) => basisCard(props, c))),
    playerInsight(props),
  )
}
