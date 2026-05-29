import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { applyFilters } from '../estimate'
import type { EstimateBasis } from '../types'
import { makeDataset, makeFilters, makeGame, makeState } from '../test/factories'
import { TimelineChart } from './TimelineChart'

function renderChart(
  count: number,
  basis: EstimateBasis = 'leisure',
  pace = 0,
) {
  const games = Array.from({ length: count }, (_, i) =>
    makeGame({ app_id: i + 1, name: `G${i}`, leisure_hours: 10 + i }),
  )
  const filters = makeFilters({ basis })
  const result = applyFilters(makeDataset(games), filters)
  return render(
    <TimelineChart
      result={result}
      filters={filters}
      state={makeState({ pace_games_per_day: pace })}
    />,
  )
}

describe('TimelineChart', () => {
  it('shows a fallback message with fewer than two games', () => {
    renderChart(1)
    expect(screen.getByText(/Not enough games/i)).toBeInTheDocument()
  })

  it('draws an SVG line for the hours basis', () => {
    const { container } = renderChart(3, 'leisure')
    expect(container.querySelector('svg.chart-svg')).not.toBeNull()
    expect(container.querySelector('path.line')).not.toBeNull()
  })

  it('draws an SVG line for the pace basis when pace is known', () => {
    const { container } = renderChart(3, 'pace', 0.5)
    expect(container.querySelector('svg.chart-svg')).not.toBeNull()
  })

  it('shows the fallback message for the pace basis with no pace', () => {
    renderChart(3, 'pace', 0)
    expect(screen.getByText(/Not enough games/i)).toBeInTheDocument()
  })

  it('renders when the last timeline point has day=0 (covers || 1 fallback)', () => {
    // Game 1: leisure_hours=0 but rush>0 so not noData → lengthHours=-1.
    // Game 2: leisure_hours=1 → lengthHours=1.
    // Cumulative with dailyHours=1: [-1, 0]. Last day=0 triggers `|| 1`.
    const games = [
      makeGame({ app_id: 1, name: 'G0', leisure_hours: 0 }),
      makeGame({ app_id: 2, name: 'G1', leisure_hours: 1 }),
    ]
    const filters = makeFilters({ basis: 'leisure', dailyHours: 1 })
    const result = applyFilters(makeDataset(games), filters)
    const { container } = render(
      <TimelineChart result={result} filters={filters} state={makeState()} />,
    )
    expect(container.querySelector('svg.chart-svg')).not.toBeNull()
  })
})
