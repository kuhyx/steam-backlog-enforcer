// The planner's headline: games in scope, the target-date banner, one card per
// estimate basis and the player's pace vs HLTB (was SummaryCards.tsx).
// Textgate: labels are glyphs (glyphs.ts), the old wording is spoken only.

import { basisTotal, etaDays, paceDays, playerEstimatedTotal, type EstimateResult } from '../../estimate'
import { fmtEta, fmtHours } from '../../format'
import { h } from '../../lib/dom'
import type { EstimateBasis, Filters, PaceVsHLTB, WebStateInfo } from '../../types'
import { empty, glyph } from '../../ui/build'
import { BASIS_GLYPH, styleGlyph } from './glyphs'

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

const spoken = (text: string) => h('span', { class: 'sr-only' }, text)
/** Games per day: the 🎮 stands in for the word "games". */
const perDay = (n: number | string) => [`${n} 🎮/d`, spoken(' games per day')]

function targetBanner({ result, filters }: SummaryProps, now: Date): HTMLDivElement | null {
  if (!filters.targetDate) return null
  const target = new Date(filters.targetDate)
  const days = Math.max(1, Math.ceil((target.getTime() - now.getTime()) / 86400000))
  // Pace is the only basis without an hours total: it needs games per day.
  const total = basisTotal(result, filters.basis)
  const need = total === null ? perDay((result.remainingGames / days).toFixed(2)) : `${(total / days).toFixed(1)} h/day`
  return h(
    'div',
    { class: 'target-banner' },
    glyph('🎮', 'To finish'),
    ' ',
    h('strong', {}, result.remainingGames),
    spoken(' games'),
    ' 🏁 ',
    spoken('by '),
    h('strong', {}, filters.targetDate),
    ` (${days} d) `,
    glyph(BASIS_GLYPH[filters.basis], `on the ${filters.basis} model, you need`),
    ' → ',
    h('strong', {}, need),
  )
}

const presetRows = (presets: readonly number[], eta: (perDay: number) => number | null) =>
  h(
    'div',
    { class: 'presets' },
    presets.map((p) => h('div', { class: 'preset' }, h('span', {}, `${p} h/day`), h('span', {}, fmtEta(eta(p))))),
  )

const pair = (icon: string, label: string, value: Node | string, attrs: Record<string, string> = {}) => [
  glyph(icon, label),
  typeof value === 'string' ? h('span', attrs, value) : value,
]

function playerInsight({ result, paceVsHltb: pace, presets }: SummaryProps): HTMLDivElement {
  const title = h('div', { class: 'player-insight-title' }, glyph(BASIS_GLYPH.pace, 'Your Play Style vs HLTB'))
  if (!pace || pace.calibration_count === 0) {
    return h(
      'div',
      { class: 'player-insight player-insight--empty' },
      title,
      empty('No calibration data yet. Finish games (100% achievements) and re-run stats to see your pace estimate.'),
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
      pair('🏆', 'Calibration games', String(pace.calibration_count)),
      pace.ratio_vs_rush !== -1
        ? pair(BASIS_GLYPH.rush, 'vs Rush speed', `${pace.ratio_vs_rush.toFixed(2)}×`, {
            class: pace.ratio_vs_rush <= 1 ? 'player-insight-fast' : 'player-insight-slow',
          })
        : null,
      pace.ratio_vs_leisure !== -1 ? pair(BASIS_GLYPH.leisure, 'vs Leisure speed', `${pace.ratio_vs_leisure.toFixed(2)}×`) : null,
      // `t` is the formula's own symbol: 0 = rush speed, 1 = leisure speed.
      pace.interpolation_t !== -1
        ? pair('t', 'Interpolation t, 0 = rush speed, 1 = leisure speed', pace.interpolation_t.toFixed(3))
        : null,
      pair('🎭', 'Play style', styleGlyph(pace.player_style)),
    ),
    estimated !== null
      ? h(
          'div',
          { class: 'player-insight-estimate' },
          h(
            'div',
            { class: 'player-insight-estimate-total' },
            glyph('Σ', 'Estimated total at your pace: '),
            ' ',
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
    { class: filters.basis === c.basis ? 'card active' : 'card', 'data-basis': c.basis },
    h('div', { class: 'card-title' }, glyph(BASIS_GLYPH[c.basis], c.title)),
    spoken(c.blurb),
    h('div', { class: 'card-total' }, isPace ? perDay(pace) : fmtHours(total)),
    h('div', { class: 'card-eta' }, isPace && !pace ? glyph('∅', 'No start date set') : fmtEta(eta)),
    isPace ? null : presetRows(presets, (p) => etaDays(total, p)),
  )
}

export function summaryCards(props: SummaryProps, now: Date = new Date()): HTMLDivElement {
  const { result, defaultQualifying } = props
  const match = result.remainingGames === defaultQualifying
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
        glyph('🎮', 'games in scope', 'big-label'),
      ),
      h(
        'div',
        { class: 'parity', 'data-match': String(match) },
        glyph('⌨️', 'CLI default qualifies '),
        ' ',
        h('strong', {}, defaultQualifying),
        match ? h('span', { class: 'ok' }, ' ✓', spoken(' match')) : null,
      ),
    ),
    targetBanner(props, now),
    h('div', { class: 'cards' }, CARDS.map((c) => basisCard(props, c))),
    playerInsight(props),
  )
}
