import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { applyFilters } from '../estimate'
import type { GameRow } from '../estimate'
import type { WebGame } from '../types'
import { makeDataset, makeFilters, makeGame } from '../test/factories'
import { GameTable } from './GameTable'

function rowsFor(games: WebGame[]): GameRow[] {
  return applyFilters(makeDataset(games), makeFilters()).rows.filter(
    (r) => r.passesFilters,
  )
}

describe('GameTable', () => {
  it('renders the row count', () => {
    const rows = rowsFor([makeGame({ app_id: 1 }), makeGame({ app_id: 2 })])
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    expect(screen.getByText(/Games \(2\)/)).toBeInTheDocument()
  })

  it('filters rows by the search prop', () => {
    const rows = rowsFor([
      makeGame({ app_id: 1, name: 'Alpha' }),
      makeGame({ app_id: 2, name: 'Beta' }),
    ])
    render(
      <GameTable
        rows={rows}
        search="alpha"
        onSearch={vi.fn()}
        onToggleExclude={vi.fn()}
      />,
    )
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
  })

  it('calls onSearch as the user types', async () => {
    const onSearch = vi.fn()
    const rows = rowsFor([makeGame({ app_id: 1, name: 'Alpha' })])
    render(
      <GameTable rows={rows} search="" onSearch={onSearch} onToggleExclude={vi.fn()} />,
    )
    await userEvent.setup().type(screen.getByPlaceholderText(/Search games/i), 'x')
    expect(onSearch).toHaveBeenCalledWith('x')
  })

  it('toggles sort direction when a header is clicked', async () => {
    const rows = rowsFor([makeGame({ app_id: 1, name: 'Alpha' })])
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    const user = userEvent.setup()
    const header = screen.getByRole('columnheader', { name: /Game/ })
    await user.click(header)
    expect(header.textContent).toContain('▲')
    await user.click(header)
    expect(header.textContent).toContain('▼')
  })

  it('invokes onToggleExclude when a keep checkbox is clicked', async () => {
    const onToggleExclude = vi.fn()
    const rows = rowsFor([makeGame({ app_id: 42, name: 'Alpha' })])
    render(
      <GameTable
        rows={rows}
        search=""
        onSearch={vi.fn()}
        onToggleExclude={onToggleExclude}
      />,
    )
    await userEvent.setup().click(screen.getByRole('checkbox'))
    expect(onToggleExclude).toHaveBeenCalledWith(42)
  })

  it('links to a direct HLTB page when the id is known, else search', () => {
    const rows = rowsFor([
      makeGame({ app_id: 1, name: 'Alpha', hltb_game_id: 555 }),
      makeGame({ app_id: 2, name: 'Beta', hltb_game_id: 0 }),
    ])
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute(
      'href',
      'https://howlongtobeat.com/game/555',
    )
    expect(screen.getByRole('link', { name: 'Beta' })).toHaveAttribute(
      'href',
      'https://howlongtobeat.com/?q=Beta',
    )
  })

  it('sorts by every column without error', async () => {
    const rows = rowsFor([
      makeGame({ app_id: 1, name: 'Alpha' }),
      makeGame({ app_id: 2, name: 'Beta' }),
    ])
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    const user = userEvent.setup()
    for (const name of [
      '%',
      'Played',
      'Rush',
      'Leisure',
      'Worst',
      'HLTB n',
      'ProtonDB',
      'Game',
    ]) {
      await user.click(screen.getByRole('columnheader', { name: new RegExp(name) }))
    }
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('shows a no-data badge for games without HLTB times', () => {
    const rows = applyFilters(
      makeDataset([
        makeGame({
          app_id: 1,
          name: 'Alpha',
          rush_hours: -1,
          leisure_hours: -1,
          worst_hours: -1,
        }),
      ]),
      makeFilters({ includeNoData: true }),
    ).rows.filter((r) => r.passesFilters)
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    expect(screen.getByText('no data')).toBeInTheDocument()
  })

  it('triggers the va > vb comparator branch when rows are reverse-sorted', async () => {
    // Gamma > Alpha alphabetically; default sort is leisure, so clicking Game header
    // causes the comparator to see va='gamma' > vb='alpha', covering cmp=1.
    const rows = rowsFor([
      makeGame({ app_id: 1, name: 'Gamma' }),
      makeGame({ app_id: 2, name: 'Alpha' }),
    ])
    render(
      <GameTable rows={rows} search="" onSearch={vi.fn()} onToggleExclude={vi.fn()} />,
    )
    await userEvent.setup().click(screen.getByRole('columnheader', { name: /Game/ }))
    // After ascending name sort Alpha comes first.
    expect(screen.getAllByRole('row')[1].textContent).toContain('Alpha')
  })

  it('caps the table and notes the overflow', () => {
    const games = Array.from({ length: 301 }, (_, i) =>
      makeGame({ app_id: i + 1, name: `Game ${i}` }),
    )
    render(
      <GameTable
        rows={rowsFor(games)}
        search=""
        onSearch={vi.fn()}
        onToggleExclude={vi.fn()}
      />,
    )
    expect(screen.getByText(/Showing first 300 of 301/i)).toBeInTheDocument()
  })
})
