import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeBudgetSession } from '../test/factories'
import { BudgetLiveCard } from './BudgetLiveCard'

describe('BudgetLiveCard', () => {
  it('reports an engaged session with its game', () => {
    render(<BudgetLiveCard session={makeBudgetSession()} />)
    expect(screen.getByText(/Billing — you are playing/)).toBeInTheDocument()
    expect(screen.getByText(/Assigned game/)).toBeInTheDocument()
    // Engaged, so the credited game is described in the present tense.
    expect(screen.getByText(/Billing to/)).toBeInTheDocument()
    expect(screen.getAllByText('Hollow Knight')).toHaveLength(2)
    expect(screen.getByText(/3 qualifying processes/)).toBeInTheDocument()
    expect(screen.getByText(/Idle 2s/)).toBeInTheDocument()
    expect(screen.getByText(/Screen held: no/)).toBeInTheDocument()
  })

  it('explains why a session is paused', () => {
    render(
      <BudgetLiveCard
        session={makeBudgetSession({
          state: 'paused',
          reason: 'focus',
          causes: ['focus', 'idle'],
          screen_held: true,
        })}
      />,
    )
    expect(screen.getByText(/Not billing — paused/)).toBeInTheDocument()
    expect(
      screen.getByText(/the game window is not focused, no input for longer/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Screen held: yes/)).toBeInTheDocument()
  })

  it('falls back to the raw cause and verdict when unrecognised', () => {
    render(
      <BudgetLiveCard
        session={makeBudgetSession({ state: 'weird', causes: ['gremlins'] })}
      />,
    )
    expect(screen.getByText('weird')).toBeInTheDocument()
    expect(screen.getByText(/gremlins/)).toBeInTheDocument()
  })

  it('omits the game line when nothing qualifies', () => {
    render(
      <BudgetLiveCard
        session={makeBudgetSession({
          state: 'not_applicable',
          qualifying_count: 0,
          processes: [],
          idle_seconds: null,
          screen_held: null,
        })}
      />,
    )
    expect(screen.getByText(/no game running/)).toBeInTheDocument()
    expect(screen.queryByText(/qualifying processes/)).toBeNull()
    expect(screen.queryByText(/Idle/)).toBeNull()
  })

  it('handles a qualifying session with no assigned game name', () => {
    render(
      <BudgetLiveCard session={makeBudgetSession({ game_name: '', billing_label: '' })} />,
    )
    expect(screen.getByText(/3 qualifying processes/)).toBeInTheDocument()
    expect(screen.queryByText('Hollow Knight')).toBeNull()
  })

  it('says when no verdict has been logged', () => {
    render(<BudgetLiveCard session={makeBudgetSession({ available: false })} />)
    expect(screen.getByText(/No verdict has been logged yet/)).toBeInTheDocument()
  })
})
