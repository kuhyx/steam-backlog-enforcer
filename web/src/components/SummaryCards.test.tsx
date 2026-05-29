import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { applyFilters } from '../estimate'
import type { Filters } from '../types'
import { makeDataset, makeFilters, makeGame, makeState } from '../test/factories'
import { SummaryCards } from './SummaryCards'

function renderCards(filtersOver: Partial<Filters> = {}, statePace = 0) {
  const filters = makeFilters(filtersOver)
  const result = applyFilters(makeDataset([makeGame({ app_id: 1 })]), filters)
  render(
    <SummaryCards
      result={result}
      filters={filters}
      state={makeState({ pace_games_per_day: statePace })}
      presets={[2, 4, 6, 8]}
      defaultQualifying={result.remainingGames}
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
