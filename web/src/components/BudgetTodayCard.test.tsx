import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeBudgetToday } from '../test/factories'
import { BudgetTodayCard } from './BudgetTodayCard'

describe('BudgetTodayCard', () => {
  it('shows remaining time, usage and the next warning', () => {
    render(<BudgetTodayCard today={makeBudgetToday()} />)
    expect(screen.getByText('7h 0m')).toBeInTheDocument()
    expect(screen.getByText(/1h 0m of 8h 0m used/)).toBeInTheDocument()
    expect(screen.getByText(/Next warning at 1h 0m remaining/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--ok')).not.toBeNull()
  })

  it('turns the meter amber once a warning has fired', () => {
    render(
      <BudgetTodayCard
        today={makeBudgetToday({ seconds_remaining: 900, warned_seconds: [3600, 1800] })}
      />,
    )
    expect(document.querySelector('.budget-meter--warn')).not.toBeNull()
  })

  it('says so when no warnings remain', () => {
    render(
      <BudgetTodayCard
        today={makeBudgetToday({
          next_warning_seconds: null,
          warned_seconds: [3600, 1800, 600, 300],
        })}
      />,
    )
    expect(screen.getByText(/No further warnings today/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--warn')).not.toBeNull()
  })

  it('shows the cutoff badge when blocked', () => {
    render(
      <BudgetTodayCard
        today={makeBudgetToday({
          blocked: true,
          blocked_at: 1,
          seconds_used: 28800,
          seconds_remaining: 0,
          fraction_used: 1,
          next_warning_seconds: null,
        })}
      />,
    )
    expect(screen.getByText(/Cutoff engaged/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--blocked')).not.toBeNull()
  })
})
