import { screen, within } from '@testing-library/dom'
import { afterEach, describe, expect, it } from 'vitest'
import { makeGame } from '../../test/factories'
import { GAMES, hash, header, names, show, table } from '../../test/plannerHelpers'
import { hltbUrl } from './plannerTable'

afterEach(() => {
  history.replaceState(null, '', '/')
})

describe('<game-table> table', () => {
  it('renders the row count', async () => {
    await show()
    expect(screen.getByText('Games (3)')).toBeInTheDocument()
  })

  it('sorts by leisure ascending by default', async () => {
    await show()
    expect(names()).toEqual(['Beta', 'Gamma', 'Alpha'])
    expect(header('Leisure')).toHaveAttribute('aria-sort', 'ascending')
    expect(header('Leisure').textContent).toBe('Leisure ▲')
  })

  it('toggles sort direction when a header is clicked', async () => {
    const { user } = await show()
    const game = header('Game')
    await user.click(game)
    expect(game.textContent).toContain('▲')
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma'])
    expect(header('Leisure')).not.toHaveAttribute('aria-sort')
    await user.click(game)
    expect(game.textContent).toContain('▼')
    expect(game).toHaveAttribute('aria-sort', 'descending')
    expect(names()).toEqual(['Gamma', 'Beta', 'Alpha'])
    expect(hash().get('sort')).toBe('name')
    expect(hash().get('dir')).toBe('desc')
  })

  it('every header sorts, and flipping it changes the first row', async () => {
    const { user } = await show()
    // One excluded game so the Keep column has two values to sort by.
    await user.click(within(table()).getAllByRole('checkbox')[1])
    for (const label of ['Game', '%', 'Played', 'Rush', 'Leisure', 'Worst', 'HLTB n', 'ProtonDB', 'Keep']) {
      await user.click(header(label))
      const first = names()[0]
      await user.click(header(label))
      expect(names()[0], label).not.toBe(first)
    }
  })

  it('filters by a typo-tolerant search and keeps focus while typing', async () => {
    const { user } = await show()
    const box = screen.getByPlaceholderText(/Search games/i)
    await user.type(box, 'gama')
    expect(names()).toEqual(['Gamma'])
    expect(document.activeElement).toBe(box)
    expect(screen.getByPlaceholderText(/Search games/i)).toBe(box)
    expect(hash().get('q')).toBe('gama')
    expect(screen.getByText('Games (1)')).toBeInTheDocument()
  })

  it('narrows rows by a text column filter without losing focus', async () => {
    const { user } = await show()
    const input = screen.getByRole('searchbox', { name: 'Filter Game' })
    await user.type(input, 'al')
    expect(names()).toEqual(['Alpha'])
    expect(document.activeElement).toBe(input)
    expect(hash().get('f.name')).toBe('al')
    await user.clear(input)
    expect(names()).toHaveLength(3)
    expect(hash().has('f.name')).toBe(false)
  })

  it('narrows rows by a numeric min/max range', async () => {
    const { user } = await show()
    const min = screen.getByRole('spinbutton', { name: 'Rush min' })
    await user.type(min, '10')
    expect(names()).toEqual(['Beta', 'Gamma'])
    expect(document.activeElement).toBe(min)
    await user.type(screen.getByRole('spinbutton', { name: 'Rush max' }), '15')
    expect(names()).toEqual(['Gamma'])
    expect(hash().get('f.rush')).toBe('10..15')
  })

  it('narrows rows by a select column', async () => {
    const { user } = await show()
    const proton = screen.getByRole('combobox', { name: 'Filter ProtonDB' })
    await user.selectOptions(proton, 'platinum')
    expect(names()).toEqual(['Beta'])
    await user.click(within(table()).getAllByRole('checkbox')[0])
    await user.selectOptions(proton, '')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Filter Keep' }), 'Excluded')
    expect(names()).toEqual(['Beta'])
    expect(hash().get('f.keep')).toBe('excluded')
  })

  it('links to a direct HLTB page when the id is known, else search', async () => {
    await show([makeGame({ app_id: 1, name: 'Alpha', hltb_game_id: 555 }), makeGame({ app_id: 2, name: 'Beta Two', hltb_game_id: 0 })])
    expect(screen.getByRole('link', { name: 'Alpha' })).toHaveAttribute('href', 'https://howlongtobeat.com/game/555')
    expect(screen.getByRole('link', { name: 'Beta Two' })).toHaveAttribute('href', 'https://howlongtobeat.com/?q=Beta%20Two')
    expect(hltbUrl(makeGame({ hltb_game_id: 7 }))).toBe('https://howlongtobeat.com/game/7')
  })

  it('formats each cell like the CLI list', async () => {
    await show(GAMES.slice(0, 1))
    const cells = [...table().querySelectorAll('tbody td')].map((td) => td.textContent)
    expect(cells.slice(0, 8)).toEqual(['Alpha', '10', '1.0 h', '5.0', '30.0', '40.0', '20', 'gold'])
  })

  it('shows a no-data badge for games without HLTB times when they are included', async () => {
    history.replaceState(null, '', '/backlog/#nodata=1')
    await show([makeGame({ app_id: 1, name: 'Alpha', rush_hours: -1, leisure_hours: -1, worst_hours: -1 })])
    expect(screen.getByText('no data')).toBeInTheDocument()
    expect(screen.getByText('Fallback estimate', { exact: false })).toBeVisible()
  })

  it('caps the table and notes the overflow', async () => {
    await show(Array.from({ length: 301 }, (_, i) => makeGame({ app_id: i + 1, name: `Game ${i}` })))
    expect(screen.getByText(/Showing first 300 of 301/i)).toBeVisible()
    expect(table().querySelectorAll('tbody tr')).toHaveLength(300)
  })

  it('hides the overflow note under the cap', async () => {
    await show()
    expect(screen.getByText(/Showing first 300/i)).not.toBeVisible()
  })
})
