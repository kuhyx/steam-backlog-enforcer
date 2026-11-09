import { describe, expect, it } from 'vitest'
import { makeDataset, makeGame } from '../test/factories'
import { makeInstalled, makeStatus } from '../test/fixtures'
import { gameLookup } from './gameLookup'

describe('gameLookup', () => {
  it('is empty until the sources load', () => {
    const { games, ctx } = gameLookup(undefined, undefined, undefined)
    expect(games).toEqual([])
    expect(ctx.gameName(1)).toBeNull()
    expect(ctx.installed).toBeNull()
  })

  it('merges backlog, installed, manual picks and the assignment, sorted by name', () => {
    const { games, ctx } = gameLookup(
      makeDataset([makeGame({ app_id: 1, name: 'Zeta' }), makeGame({ app_id: 2, name: 'Old name' })]),
      { games: [makeInstalled({ app_id: 2, name: 'Beta' })] },
      makeStatus({ current_app_id: 4, current_game_name: 'Delta', manual_picks: [{ app_id: 3, name: 'Gamma', age_days: 1 }] }),
    )
    expect(games.map((g) => g.name)).toEqual(['Beta', 'Delta', 'Gamma', 'Zeta'])
    expect(ctx.gameName(2)).toBe('Beta')
    expect(ctx.installed).toHaveLength(1)
  })

  it('skips an unassigned status', () => {
    const base = [makeGame({ app_id: 1, name: 'Zeta' })]
    const none = gameLookup(makeDataset(base), undefined, makeStatus({ current_app_id: null, current_game_name: null }))
    expect(none.games).toHaveLength(1)
    const nameless = gameLookup(makeDataset(base), undefined, makeStatus({ current_app_id: 9, current_game_name: '' }))
    expect(nameless.games).toHaveLength(1)
  })
})
