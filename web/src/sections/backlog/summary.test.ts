import { getAllByText, getByText, queryByText } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { applyFilters } from '../../estimate'
import { makeDataset, makeFilters, makeGame, makePaceVsHltb, makeState } from '../../test/factories'
import type { Filters, PaceVsHLTB } from '../../types'
import { painted } from './painted.testutil'
import { summaryCards } from './summary'

const NOW = new Date('2026-01-01T00:00:00Z')

function cards(over: Partial<Filters> = {}, statePace = 0, paceVsHltb: PaceVsHLTB | null = null, qualifying?: number) {
  const filters = makeFilters(over)
  const result = applyFilters(makeDataset([makeGame({ app_id: 1 })]), filters)
  const el = summaryCards(
    {
      result,
      filters,
      state: makeState({ pace_games_per_day: statePace }),
      presets: [2, 4, 6, 8],
      defaultQualifying: qualifying ?? result.remainingGames,
      paceVsHltb,
    },
    NOW,
  )
  document.body.append(el)
  return el
}

describe('summaryCards', () => {
  it('shows the in-scope count and a CLI-parity match badge', () => {
    const el = cards()
    expect(getByText(el, /games in scope/i)).toBeInTheDocument()
    expect(el.querySelector('.big')?.textContent).toBe('1')
    expect(getByText(el, /match/i)).toBeInTheDocument()
  })

  it('drops the match badge when the count differs from the CLI', () => {
    const el = cards({}, 0, null, 7)
    expect(painted(el.querySelector('.parity'))).toBe('⌨️ 7')
    expect(el.querySelector('.parity')).toHaveAttribute('data-match', 'false')
  })

  it('marks the active basis card and lists presets for hour bases only', () => {
    const el = cards({ basis: 'rush' })
    expect(el.querySelector('.card.active')).toHaveAttribute('data-basis', 'rush')
    expect(painted(el.querySelector('.card.active .card-title'))).toBe('🐇')
    expect(el.querySelectorAll('.cards .card')).toHaveLength(4)
    expect(el.querySelectorAll('.cards .presets')).toHaveLength(3)
    expect(el.querySelector('.card .card-total')?.textContent).toBe('10 h')
  })

  it('notes a missing start date in the pace card', () => {
    expect(getByText(cards({}, 0), /No start date set/i)).toBeInTheDocument()
  })

  it('shows the pace card ETA when a pace is known', () => {
    const el = cards({}, 0.5)
    const pace = [...el.querySelectorAll('.card')].at(-1)
    expect(painted(pace?.querySelector('.card-total'))).toBe('0.5 🎮/d')
    expect(pace?.querySelector('.card-eta')?.textContent).toMatch(/^2 days · /)
  })

  it('renders the target-date banner with required hours/day', () => {
    const banner = cards({ targetDate: '2026-01-11', basis: 'leisure' }).querySelector('.target-banner')
    expect(painted(banner)).toBe('🎮 1 🏁 2026-01-11 (10 d) 🐢 → 2.0 h/day')
    expect(banner).toHaveTextContent(/on the leisure model, you need/)
  })

  it('renders the target banner in games/day for the pace basis', () => {
    const banner = cards({ targetDate: '2099-01-01', basis: 'pace' }, 0.9).querySelector('.target-banner')
    expect(painted(banner)).toMatch(/👤 → [\d.]+ 🎮\/d$/)
  })

  it('counts a past target as one day', () => {
    expect(painted(cards({ targetDate: '2020-01-01' }).querySelector('.target-banner'))).toMatch(/\(1 d\)/)
  })

  it('defaults the clock to now', () => {
    const result = applyFilters(makeDataset(), makeFilters())
    const el = summaryCards({ result, filters: makeFilters(), state: makeState(), presets: [], defaultQualifying: 1, paceVsHltb: null })
    expect(el.querySelector('.target-banner')).toBeNull()
  })
})

describe('player insight', () => {
  it('shows the empty state when paceVsHltb is null', () => {
    const el = cards({}, 0, null)
    expect(getByText(el, /Your Play Style vs HLTB/i)).toBeInTheDocument()
    expect(getByText(el, /No calibration data yet/i)).toBeInTheDocument()
  })

  it('shows the empty state with zero calibration games', () => {
    expect(getByText(cards({}, 0, makePaceVsHltb({ calibration_count: 0 })), /No calibration data yet/i)).toBeInTheDocument()
  })

  it('shows calibration stats when paceVsHltb is provided', () => {
    const el = cards({}, 0, makePaceVsHltb())
    expect(getByText(el, /Calibration games/i)).toBeInTheDocument()
    expect(getByText(el, /vs Rush speed/i)).toBeInTheDocument()
    expect(getByText(el, 'Play style')).toBeInTheDocument()
    const style = el.querySelector('.player-insight-style--rush_to_leisure')
    expect(style).toHaveTextContent(/Between rush and leisure/)
    expect(painted(style)).toBe('🐇↔🐢')
    expect(getByText(el, '1.05×')).toHaveClass('player-insight-slow')
    expect(getByText(el, '0.050')).not.toHaveAttribute('title')
    expect(getByText(el, /0 = rush speed, 1 = leisure speed/)).toHaveClass('sr-only')
  })

  it('shows the estimated total at the player’s pace', () => {
    // rush 10, leisure 20, t = 0.05 → 10.5 h
    const el = cards({}, 0, makePaceVsHltb({ interpolation_t: 0.05 }))
    expect(el.querySelector('.player-insight-estimate-hours')?.textContent).toBe('11 h')
    expect(el.querySelectorAll('.player-insight-estimate .preset')).toHaveLength(4)
  })

  it('hides the leisure ratio and t when they are -1', () => {
    const el = cards({}, 0, makePaceVsHltb({ ratio_vs_leisure: -1, interpolation_t: -1 }))
    expect(queryByText(el, /vs Leisure speed/i)).toBeNull()
    expect(queryByText(el, /Interpolation t/i)).toBeNull()
  })

  it('hides the rush ratio and the estimate when nothing is known', () => {
    const el = cards({}, 0, makePaceVsHltb({ ratio_vs_rush: -1, interpolation_t: -1 }))
    expect(queryByText(el, /vs Rush speed/i)).toBeNull()
    expect(queryByText(el, /Estimated total/i)).toBeNull()
  })

  it('marks the rush ratio as fast when at or below 1', () => {
    expect(getByText(cards({}, 0, makePaceVsHltb({ ratio_vs_rush: 0.9 })), '0.90×')).toHaveClass('player-insight-fast')
  })

  it('falls back to the raw player_style key when it has no display label', () => {
    const pace = makePaceVsHltb({ player_style: 'totally_unknown' as PaceVsHLTB['player_style'] })
    expect(getByText(cards({}, 0, pace), 'totally_unknown')).toBeInTheDocument()
  })

  it('shows N/A presets when the estimated pace total is not positive', () => {
    const el = cards({ excluded: new Set([1]) }, 0, makePaceVsHltb())
    expect(getByText(el, /Estimated total at your pace/i)).toBeInTheDocument()
    expect(getAllByText(el, 'N/A').length).toBeGreaterThan(0)
  })
})
