import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeBudgetRules, makeBudgetToday } from '../../test/factories'
import { rulesCard, todayCard } from './cards'

const show = (el: HTMLElement) => {
  document.body.replaceChildren(el)
}

// From 2026-11-16 the backend sends no budget number at all.
const unlimitedToday = () =>
  makeBudgetToday({
    unlimited: true,
    budget_seconds: null,
    seconds_remaining: null,
    fraction_used: null,
    next_warning_seconds: null,
    seconds_used: 40_000,
  })

describe('unlimited day', () => {
  it('paints infinity, no meter, no warning line, no percentage', () => {
    show(todayCard(unlimitedToday(), [], 0))
    expect(screen.getByText('∞')).toBeInTheDocument()
    expect(document.querySelector('.budget-meter')).toBeNull()
    expect(document.body.textContent).not.toMatch(/warning/i)
    expect(document.querySelector('.budget-hero')?.textContent).not.toMatch(/%|left/)
    expect(document.querySelector('.hint')?.textContent).not.toMatch(/%/)
    expect(document.body.textContent).toContain('11h 6m')
  })

  it('keeps showing what was billed, by game', () => {
    show(todayCard(unlimitedToday(), [], 0))
    expect(screen.getByText('Hollow Knight')).toBeInTheDocument()
  })

  it('rules: no daily budget and no warning thresholds', () => {
    show(rulesCard(makeBudgetRules({ unlimited: true, budget_seconds: null, warn_at: [] })))
    expect(screen.getByText('∞')).toBeInTheDocument()
    expect(screen.queryByText('Warnings at')).toBeNull()
  })

  it('an enforced day still has its meter', () => {
    show(todayCard(makeBudgetToday(), [], 0))
    expect(document.querySelector('.budget-meter')).not.toBeNull()
  })
})
