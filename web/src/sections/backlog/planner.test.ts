import { screen, within } from '@testing-library/dom'
import { afterEach, describe, expect, it } from 'vitest'
import { q } from '../../api/queries'
import { makeDataset, makeGame, makeState } from '../../test/factories'
import { big, GAMES, hash, header, names, panel, show, table } from '../../test/plannerHelpers'

afterEach(() => {
  history.replaceState(null, '', '/')
})

describe('<game-table> planner', () => {
  it('heads with the current game, finished count, start date and candidates', async () => {
    await show(GAMES, {
      state: makeState({ current_game_name: 'Hollow Knight', games_done_since_start: 3, enforcement_started_at: '2026-03-04T00:00:00+00:00' }),
    })
    expect(document.querySelector('.app-head .sub')?.textContent).toBe(
      'Currently playing Hollow Knight · 3 games finished since 2026-03-04 · 3 candidates',
    )
  })

  it('dashes a missing start date', async () => {
    await show()
    expect(document.querySelector('.app-head .sub')?.textContent).toBe('0 games finished since — · 3 candidates')
  })

  it('recomputes scope when basis changes and a game is excluded', async () => {
    const { user } = await show(GAMES.slice(0, 2), { state: makeState({ pace_games_per_day: 0.9 }) })
    expect(big()).toBe('2')
    await user.click(panel().getByRole('button', { name: 'Rush' }))
    expect(document.querySelector('.card.active .card-title')?.textContent).toBe('Rush')
    expect(document.querySelector('.chart h2')?.textContent).toBe('Completion timeline · rush')
    expect(hash().get('basis')).toBe('rush')

    const box = within(table()).getAllByRole('checkbox')[0]
    await user.click(box)
    expect(big()).toBe('1')
    expect(box.closest('tr')).toHaveClass('excluded')
    expect(box).toHaveAccessibleName('Re-include')
    expect(document.activeElement).toBe(box)
    expect(hash().get('x')).not.toBeNull()
    await user.click(box)
    expect(big()).toBe('2')
    expect(box.closest('tr')).not.toHaveClass('excluded')

    await user.type(screen.getByPlaceholderText(/Search games/i), 'Alpha')
    expect(names()).toEqual(['Alpha'])

    await user.click(screen.getByRole('button', { name: /Reset to CLI defaults/i }))
    expect(big()).toBe('2')
    expect(names()).toHaveLength(2)
    expect(screen.getByPlaceholderText(/Search games/i)).toHaveValue('')
    expect(location.hash).toBe('')
  })

  it('updates the slider readout and the hash as a slider moves', async () => {
    await show()
    const daily = screen.getByRole('slider', { name: 'Daily play time' })
    daily.focus()
    ;(daily as HTMLInputElement).value = '8'
    daily.dispatchEvent(new Event('input'))
    expect(panel().getByText('8 h/day')).toHaveClass('val')
    expect(document.activeElement).toBe(daily)
    expect(hash().get('daily')).toBe('8')
  })

  it('keeps every filter when a newer dataset arrives', async () => {
    const { user } = await show()
    await user.type(screen.getByRole('searchbox', { name: 'Filter Game' }), 'a')
    q.dataset.set(makeDataset([...GAMES, makeGame({ app_id: 4, name: 'Delta', protondb_tier: 'native', protondb_trending_tier: '' })]))
    expect(screen.getByRole('searchbox', { name: 'Filter Game' })).toHaveValue('a')
    expect(names()).toContain('Delta')
    expect(document.querySelector('.app-head .sub')?.textContent).toMatch(/4 candidates/)
    const proton = screen.getByRole('combobox', { name: 'Filter ProtonDB' })
    expect([...(proton as HTMLSelectElement).options].map((o) => o.value)).toEqual(['', 'gold', 'gold / platinum', 'native', 'platinum'])
  })

  it('drops the hash once the sort is back to the default', async () => {
    const { user } = await show()
    await user.click(header('Leisure'))
    expect(location.hash).toBe('#sort=leisure&dir=desc')
    await user.click(header('Leisure'))
    expect(location.hash).toBe('')
  })

  it('restores sort, search, column and planner filters from the hash on load', async () => {
    history.replaceState(null, '', '/backlog/#sort=name&dir=desc&q=a&f.rush=1..15&f.proton=gold&basis=worst')
    await show()
    expect(screen.getByPlaceholderText(/Search games/i)).toHaveValue('a')
    expect(screen.getByRole('spinbutton', { name: 'Rush min' })).toHaveValue(1)
    expect(screen.getByRole('spinbutton', { name: 'Rush max' })).toHaveValue(15)
    expect(screen.getByRole('combobox', { name: 'Filter ProtonDB' })).toHaveValue('gold')
    expect(header('Game').textContent).toBe('Game ▼')
    expect(panel().getByRole('button', { name: 'Worst' })).toHaveClass('active')
    expect(names()).toEqual(['Alpha'])
  })
})
