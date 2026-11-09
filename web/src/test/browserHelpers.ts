// Shared helpers for the <game-browser> tests. Lives under src/test/,
// excluded from the app build and from coverage.

import { screen, within } from '@testing-library/dom'
import '../library/gameBrowser'
import type { GameBrowserElement, PickMode } from '../library/pick'
import { makeLibGame } from './fixtures'
import { mount, stubApi } from './harness'

export const GAMES = [
  makeLibGame({ app_id: 1, name: 'The Witcher', achievements_unlocked: 10, last_played: 100, hltb_hours: 30 }),
  makeLibGame({ app_id: 2, name: 'The Witcher 2', achievements_unlocked: 2, last_played: 300, hltb_hours: 20, installed: true }),
  makeLibGame({ app_id: 3, name: 'The Witcher 3', achievements_unlocked: 5, last_played: null, hltb_hours: null, ineligible_reason: 'Already started' }),
  makeLibGame({ app_id: 4, name: 'Age of Empires III', achievements_unlocked: 5, last_played: 200, hltb_hours: 10 }),
  makeLibGame({ app_id: 5, name: 'Hollow Knight', achievements_unlocked: 1, last_played: 50, hltb_hours: 5 }),
]
export const withLibrary = (games = GAMES) => stubApi({ 'GET /api/library': { games } })

export const at = (url: string) => {
  history.replaceState(null, '', url)
}

export function render(pick?: PickMode, attrs = ''): GameBrowserElement {
  const el = mount(`<game-browser ${attrs}></game-browser>`) as GameBrowserElement
  if (pick) el.pick = pick
  return el
}
export const grid = () => screen.getByRole('group', { name: 'Games' })
export const titles = () => [...grid().querySelectorAll('.game-title')].map((t) => t.textContent)
export const card = (name: string) => {
  const [title] = within(grid()).getAllByText(name, { selector: '.game-title' })
  const btn = title.closest('button')
  if (!btn) throw new Error(`no card ${name}`)
  return btn
}
export const search = () => screen.getByRole('combobox', { name: 'Search your games' })
export const sort = () => screen.getByRole('combobox', { name: 'Sort' })
