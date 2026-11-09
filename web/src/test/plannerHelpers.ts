// Shared helpers for the <game-table> tests. Lives under src/test/,
// excluded from the app build and from coverage.

import { screen, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import '../sections/backlog/index'
import type { WebDataset, WebGame } from '../types'
import { makeDataset, makeGame } from './factories'
import { flush, mount, stubApi } from './harness'

export const GAMES: WebGame[] = [
  makeGame({ app_id: 1, name: 'Alpha', completion_pct: 10, playtime_minutes: 60, rush_hours: 5, leisure_hours: 30, worst_hours: 40, count_comp: 20, protondb_tier: 'gold', protondb_trending_tier: 'gold', protondb_score: 0.9 }),
  makeGame({ app_id: 2, name: 'Beta', completion_pct: 50, playtime_minutes: 0, rush_hours: 20, leisure_hours: 10, worst_hours: 60, count_comp: 50, protondb_tier: 'platinum', protondb_trending_tier: 'platinum', protondb_score: 0.3 }),
  makeGame({ app_id: 3, name: 'Gamma', completion_pct: 30, playtime_minutes: 300, rush_hours: 10, leisure_hours: 20, worst_hours: 50, count_comp: 30, protondb_tier: 'gold', protondb_trending_tier: 'platinum', protondb_score: 0.6 }),
]

export async function show(games: WebGame[] = GAMES, over: Partial<WebDataset> = {}) {
  stubApi({ 'GET /api/dataset': makeDataset(games, over) })
  const el = mount('<game-table></game-table>')
  await flush()
  return { el, user: userEvent.setup() }
}
export const table = () => screen.getByRole('table')
export const names = () => [...table().querySelectorAll('tbody td.name a')].map((a) => a.textContent)
export const header = (name: string) => screen.getByRole('columnheader', { name: new RegExp(`^${name.replace(/[%]/g, '\\$&')}( [▲▼])?$`) })
export const panel = () => within(screen.getByRole('complementary'))
export const big = () => document.querySelector('.big')?.textContent
export const hash = () => new URLSearchParams(location.hash.slice(1))
