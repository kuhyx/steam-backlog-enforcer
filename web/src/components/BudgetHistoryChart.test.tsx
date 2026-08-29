import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BudgetHistoryDay, BudgetLegendEntry } from '../types'
import { BudgetHistoryChart } from './BudgetHistoryChart'

const LEGEND: BudgetLegendEntry[] = [
  { key: 'app:475150', label: 'Titan Quest' },
  { key: 'proc:osu-lazer', label: 'osu!lazer' },
  { key: 'unattributed', label: 'Unattributed' },
]

function day(over: Partial<BudgetHistoryDay> = {}): BudgetHistoryDay {
  return {
    day: '2026-08-28',
    seconds: 14400,
    segments: [{ key: 'app:475150', seconds: 14400 }],
    ...over,
  }
}

describe('BudgetHistoryChart', () => {
  it('explains itself when nothing has been recorded', () => {
    render(<BudgetHistoryChart days={[]} legend={[]} budgetSeconds={28800} />)
    expect(screen.getByText(/No budget history recorded yet/)).toBeInTheDocument()
    expect(document.querySelector('svg')).toBeNull()
  })

  it('draws a single day without filling the plot', () => {
    render(<BudgetHistoryChart days={[day()]} legend={LEGEND} budgetSeconds={28800} />)
    const bars = document.querySelectorAll('rect.seg')
    expect(bars).toHaveLength(1)
    // Scaled against the budget, half a budget is half the plot height.
    expect(Number(bars[0].getAttribute('height'))).toBeLessThan(
      Number(document.querySelector('svg')?.getAttribute('viewBox')?.split(' ')[3]) / 2,
    )
    expect(screen.getByText('08-28')).toBeInTheDocument()
  })

  it('stacks one band per game and colours it by legend position', () => {
    render(
      <BudgetHistoryChart
        days={[
          day({
            seconds: 21600,
            segments: [
              { key: 'app:475150', seconds: 14400 },
              { key: 'proc:osu-lazer', seconds: 7200 },
            ],
          }),
        ]}
        legend={LEGEND}
        budgetSeconds={28800}
      />,
    )
    expect(document.querySelectorAll('rect.seg')).toHaveLength(2)
    expect(document.querySelector('rect.cat-1')).not.toBeNull()
    expect(document.querySelector('rect.cat-2')).not.toBeNull()
    // Bands abut: the second starts exactly where the first ends.
    const [first, second] = document.querySelectorAll('rect.seg')
    const firstTop = Number(first.getAttribute('y'))
    const secondBottom =
      Number(second.getAttribute('y')) + Number(second.getAttribute('height'))
    expect(secondBottom).toBeCloseTo(firstTop, 5)
  })

  it('renders an unattributed day in its own neutral band', () => {
    render(
      <BudgetHistoryChart
        days={[
          day({
            day: '2026-08-24',
            seconds: 12000,
            segments: [{ key: 'unattributed', seconds: 12000 }],
          }),
        ]}
        legend={LEGEND}
        budgetSeconds={28800}
      />,
    )
    expect(document.querySelectorAll('rect.seg.unattributed')).toHaveLength(1)
    // No ramp hue: an absence of information must not read as another game.
    expect(document.querySelector('rect.cat-1')).toBeNull()
  })

  it('labels each band with its game in the tooltip and the legend', () => {
    render(<BudgetHistoryChart days={[day()]} legend={LEGEND} budgetSeconds={28800} />)
    expect(document.querySelector('rect.seg title')?.textContent).toContain('Titan Quest')
    expect(document.querySelectorAll('.chart-legend li')).toHaveLength(LEGEND.length)
  })

  it('falls back to the raw key when the legend omits it', () => {
    render(
      <BudgetHistoryChart
        days={[day({ segments: [{ key: 'app:999', seconds: 3600 }] })]}
        legend={LEGEND}
        budgetSeconds={28800}
      />,
    )
    expect(document.querySelector('rect.seg title')?.textContent).toContain('app:999')
  })

  it('survives a zero budget and a day that billed nothing', () => {
    render(
      <BudgetHistoryChart
        days={[day({ seconds: 0, segments: [] })]}
        legend={[]}
        budgetSeconds={0}
      />,
    )
    // A day with no billed time draws no bands, but the axes still render.
    expect(document.querySelectorAll('rect.seg')).toHaveLength(0)
    expect(document.querySelector('svg')).not.toBeNull()
  })
})
