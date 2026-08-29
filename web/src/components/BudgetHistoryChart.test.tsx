import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BudgetHistoryChart } from './BudgetHistoryChart'

describe('BudgetHistoryChart', () => {
  it('explains itself when nothing has been recorded', () => {
    render(<BudgetHistoryChart days={[]} budgetSeconds={28800} />)
    expect(screen.getByText(/No budget history recorded yet/)).toBeInTheDocument()
    expect(document.querySelector('svg')).toBeNull()
  })

  it('draws a single day without filling the plot', () => {
    render(
      <BudgetHistoryChart days={[{ day: '2026-08-28', seconds: 14400 }]} budgetSeconds={28800} />,
    )
    const bars = document.querySelectorAll('rect.bar')
    expect(bars).toHaveLength(1)
    // Scaled against the budget, half a budget is half the plot height.
    expect(Number(bars[0].getAttribute('height'))).toBeLessThan(
      Number(document.querySelector('svg')?.getAttribute('viewBox')?.split(' ')[3]) / 2,
    )
    expect(screen.getByText('08-28')).toBeInTheDocument()
  })

  it('marks a day that reached the budget', () => {
    render(
      <BudgetHistoryChart
        days={[
          { day: '2026-08-27', seconds: 3600 },
          { day: '2026-08-28', seconds: 28800 },
        ]}
        budgetSeconds={28800}
      />,
    )
    expect(document.querySelectorAll('rect.bar')).toHaveLength(2)
    expect(document.querySelectorAll('rect.bar.over')).toHaveLength(1)
  })

  it('survives a zero budget and zero seconds', () => {
    render(<BudgetHistoryChart days={[{ day: '2026-08-28', seconds: 0 }]} budgetSeconds={0} />)
    expect(document.querySelectorAll('rect')).toHaveLength(1)
  })
})
