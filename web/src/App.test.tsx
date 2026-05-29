import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { makeDataset, makeGame, makeState } from './test/factories'

describe('App', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the planner after data loads', async () => {
    const ds = makeDataset([makeGame({ app_id: 1, name: 'Alpha' })])
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ds }),
    )
    render(<App />)
    expect(screen.getByText(/Loading your backlog/i)).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Backlog Completion Planner' }),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/CLI default qualifies/i)).toBeInTheDocument()
  })

  it('shows an error when the API call fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'Server Error' }),
    )
    render(<App />)
    await waitFor(() =>
      expect(screen.getByText(/Could not load data/i)).toBeInTheDocument(),
    )
  })

  it('handles a non-Error rejection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('network down'))
    render(<App />)
    await waitFor(() =>
      expect(screen.getByText(/network down/i)).toBeInTheDocument(),
    )
  })

  it('recomputes scope when basis changes and a game is excluded', async () => {
    const ds = makeDataset(
      [makeGame({ app_id: 1, name: 'Alpha' }), makeGame({ app_id: 2, name: 'Beta' })],
      {
        state: makeState({
          current_game_name: 'Hollow Knight',
          enforcement_started_at: '2026-03-04T00:00:00+00:00',
          pace_games_per_day: 0.9,
        }),
      },
    )
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ds }),
    )
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: 'Backlog Completion Planner' }),
      ).toBeInTheDocument(),
    )
    // The current game appears in the header (covers the conditional branch).
    expect(screen.getByText(/Hollow Knight/)).toBeInTheDocument()
    expect(document.querySelector('.big')?.textContent).toBe('2')

    // Switching basis promotes the Rush card to active.
    await user.click(screen.getByRole('button', { name: 'Rush' }))
    expect(document.querySelector('.card.active .card-title')?.textContent).toBe('Rush')

    // Excluding a game drops the in-scope count.
    await user.click(within(screen.getByRole('table')).getAllByRole('checkbox')[0])
    expect(document.querySelector('.big')?.textContent).toBe('1')

    // Re-including it restores the count (covers the toggle-off branch).
    await user.click(within(screen.getByRole('table')).getAllByRole('checkbox')[0])
    expect(document.querySelector('.big')?.textContent).toBe('2')

    // Searching narrows the table (covers the search handler).
    await user.type(screen.getByPlaceholderText(/Search games/i), 'Alpha')
    expect(within(screen.getByRole('table')).queryByText('Beta')).toBeNull()

    // Reset restores the full scope (covers the reset handler).
    await user.click(screen.getByRole('button', { name: /Reset to CLI defaults/i }))
    expect(document.querySelector('.big')?.textContent).toBe('2')
  })
})
