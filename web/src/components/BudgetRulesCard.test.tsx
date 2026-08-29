import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeBudgetRules } from '../test/factories'
import { BudgetRulesCard } from './BudgetRulesCard'

describe('BudgetRulesCard', () => {
  it('lists the production policy', () => {
    render(<BudgetRulesCard rules={makeBudgetRules()} />)
    expect(screen.getByText('8h 0m')).toBeInTheDocument()
    expect(screen.getByText('on')).toBeInTheDocument()
    expect(screen.getByText(/idle grace 5m/)).toBeInTheDocument()
    expect(screen.getByText(/game must be focused/)).toBeInTheDocument()
    expect(screen.getByText('yes')).toBeInTheDocument()
    expect(screen.getByText(/1h 0m, 30m, 10m, 5m remaining/)).toBeInTheDocument()
    expect(screen.queryByText(/demo/)).toBeNull()
    expect(screen.queryByText('Masked now')).toBeNull()
  })

  it('shows the demo mode and masked launchers when they apply', () => {
    render(
      <BudgetRulesCard
        rules={makeBudgetRules({
          enforcement: false,
          counts_launchers: false,
          engagement_gate: false,
          require_game_focus: false,
          demo: true,
          masked_launchers: ['/usr/bin/steam'],
        })}
      />,
    )
    expect(screen.getByText(/demo \(short budget/)).toBeInTheDocument()
    expect(screen.getByText('/usr/bin/steam')).toBeInTheDocument()
    expect(screen.getByText('no')).toBeInTheDocument()
    expect(screen.queryByText(/game must be focused/)).toBeNull()
  })
})
