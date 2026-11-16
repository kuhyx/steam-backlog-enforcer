import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeBudget, makeBudgetToday } from '../test/factories'
import { mount, stubApi } from '../test/harness'
import './dashboard'

// From 2026-11-16 the backend sends no budget number: the glance paints the
// no-limit mark and no bar, and still says what is billing.
describe('budget glance on an unlimited day', () => {
  it('shows the no-limit mark, no progress bar, and the billing line', async () => {
    const today = makeBudgetToday({ unlimited: true, budget_seconds: null, seconds_remaining: null, fraction_used: null })
    stubApi({ 'GET /api/budget': makeBudget({ today }) })
    mount('<budget-glance></budget-glance>')
    expect(await screen.findByText('∞')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar', { name: 'Budget used' })).toBeNull()
    expect(screen.getByText('Now: Hollow Knight')).toBeInTheDocument()
  })
})
