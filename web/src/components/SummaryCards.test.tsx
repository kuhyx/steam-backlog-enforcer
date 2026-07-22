import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { applyFilters } from '../estimate'
import type { Filters } from '../types'
import { makeDataset, makeFilters, makeGame, makePaceVsHltb, makeState } from '../test/factories'
import { SummaryCards } from './SummaryCards'

function renderCards(filtersOver: Partial<Filters> = {}, statePace = 0, paceVsHltb = null) {
  const filters = makeFilters(filtersOver)
  const dataset = makeDataset([makeGame({ app_id: 1 })], { pace_vs_hltb: paceVsHltb })
  const result = applyFilters(dataset, filters)
  render(
    <SummaryCards
      result={result}
      filters={filters}
      state={makeState({ pace_games_per_day: statePace })}
      presets={[2, 4, 6, 8]}
      defaultQualifying={result.remainingGames}
      paceVsHltb={paceVsHltb}
    />,
  )
  return result
}

describe('SummaryCards', () => {
  it('shows the in-scope count and a CLI-parity match badge', () => {
    renderCards()
    expect(screen.getByText(/games in scope/i)).toBeInTheDocument()
    expect(screen.getByText(/match/i)).toBeInTheDocument()
  })

  it('notes a missing start date in the pace card', () => {
    renderCards({}, 0)
    expect(screen.getByText(/No start date set/i)).toBeInTheDocument()
  })

  it('renders the target-date banner with required hours/day', () => {
    renderCards({ targetDate: '2099-01-01', basis: 'leisure' })
    const banner = document.querySelector('.target-banner')
    expect(banner?.textContent).toMatch(/you need/i)
    expect(banner?.textContent).toMatch(/h\/day/i)
  })

  it('renders the target banner in games/day for the pace basis', () => {
    renderCards({ targetDate: '2099-01-01', basis: 'pace' }, 0.9)
    const banner = document.querySelector('.target-banner')
    expect(banner?.textContent).toMatch(/games\/day/i)
  })
})

describe('PlayerSpeedInsight', () => {
  it('shows empty state message when paceVsHltb is null', () => {
    renderCards({}, 0, null)
    expect(screen.getByText(/Your Play Style vs HLTB/i)).toBeInTheDocument()
    expect(screen.getByText(/No calibration data yet/i)).toBeInTheDocument()
  })

  it('shows calibration stats when paceVsHltb is provided', () => {
    renderCards({}, 0, makePaceVsHltb())
    expect(screen.getByText(/Calibration games/i)).toBeInTheDocument()
    expect(screen.getByText(/vs Rush speed/i)).toBeInTheDocument()
    expect(screen.getByText('Play style')).toBeInTheDocument()
    expect(screen.getByText(/Between rush and leisure/i)).toBeInTheDocument()
  })

  it('shows estimated total when calibration data is present', () => {
    // rushTotal = 10, leisureTotal = 20, t = 0.05 → 10 + 0.05 * 10 = 10.5 h
    renderCards({}, 0, makePaceVsHltb({ interpolation_t: 0.05 }))
    expect(screen.getByText(/Estimated total at your pace/i)).toBeInTheDocument()
  })

  it('hides leisure ratio when ratio_vs_leisure is -1', () => {
    renderCards({}, 0, makePaceVsHltb({ ratio_vs_leisure: -1, interpolation_t: -1 }))
    expect(screen.queryByText(/vs Leisure speed/i)).not.toBeInTheDocument()
  })

  it('marks the rush ratio as fast when at or below 1', () => {
    renderCards({}, 0, makePaceVsHltb({ ratio_vs_rush: 0.9 }))
    expect(screen.getByText('0.90×')).toHaveClass('player-insight-fast')
  })

  it('falls back to the raw player_style key when it has no display label', () => {
    renderCards({}, 0, makePaceVsHltb({ player_style: 'totally_unknown' }))
    expect(screen.getByText('totally_unknown')).toBeInTheDocument()
  })

  it('shows N/A presets when the estimated pace total is not positive', () => {
    renderCards({ excluded: new Set([1]) }, 0, makePaceVsHltb())
    expect(screen.getByText(/Estimated total at your pace/i)).toBeInTheDocument()
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0)
  })
})
