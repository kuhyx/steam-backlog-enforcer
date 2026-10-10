import { describe, expect, it } from 'vitest'
import { makeLibGame } from '../test/fixtures'
import { completion, filterGames, isCompleted, metaLine, NO_FILTERS, sortGames } from './view'

const g = makeLibGame

describe('completion', () => {
  it('is a percentage, or null without achievements', () => {
    expect(completion(g({ achievements_total: 8, achievements_unlocked: 2 }))).toBe(25)
    expect(completion(g({ achievements_total: 0 }))).toBeNull()
  })

  it('isCompleted needs achievements and all of them', () => {
    expect(isCompleted(g({ achievements_total: 4, achievements_unlocked: 4 }))).toBe(true)
    expect(isCompleted(g({ achievements_total: 4, achievements_unlocked: 3 }))).toBe(false)
    expect(isCompleted(g({ achievements_total: 0, achievements_unlocked: 0 }))).toBe(false)
  })
})

describe('sortGames', () => {
  const a = g({ app_id: 1, name: 'Bravo', last_played: 100, hltb_hours: 30, achievements_unlocked: 1 })
  const b = g({ app_id: 2, name: 'Alpha', last_played: 200, hltb_hours: 5, achievements_unlocked: 9 })
  const c = g({ app_id: 3, name: 'Charlie', last_played: null, hltb_hours: null, achievements_total: 0 })
  const d = g({ app_id: 4, name: 'Delta', last_played: null, hltb_hours: null, achievements_total: 0 })
  const names = (key: Parameters<typeof sortGames>[1]) => sortGames([c, a, d, b], key).map((x) => x.name)

  it('sorts by name', () => expect(names('name')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']))
  it('sorts recent first, never-played last', () =>
    expect(names('recent')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']))
  it('sorts by completion descending, unknown last', () =>
    expect(names('completion')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']))
  it('sorts shortest HLTB first, unknown last', () =>
    expect(names('hltb')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']))

  it('does not mutate its input', () => {
    const input = [b, a]
    sortGames(input, 'name')
    expect(input).toEqual([b, a])
  })
})

describe('filterGames', () => {
  const done = g({ app_id: 1, achievements_total: 2, achievements_unlocked: 2, installed: true })
  const open = g({ app_id: 2, installed: false })
  const all = [done, open]
  const pickable = (x: { app_id: number }) => x.app_id === 2

  it('keeps everything without filters', () => {
    expect(filterGames(all, NO_FILTERS, pickable)).toEqual(all)
  })
  it('hides completed', () => {
    expect(filterGames(all, { ...NO_FILTERS, hideCompleted: true }, pickable)).toEqual([open])
  })
  it('keeps installed only', () => {
    expect(filterGames(all, { ...NO_FILTERS, installedOnly: true }, pickable)).toEqual([done])
  })
  it('keeps pickable only', () => {
    expect(filterGames(all, { ...NO_FILTERS, pickableOnly: true }, pickable)).toEqual([open])
  })
})

describe('metaLine', () => {
  it('joins percentage, HLTB and playtime', () => {
    expect(metaLine(g({ achievements_total: 8, achievements_unlocked: 3, hltb_hours: 12, playtime_minutes: 192 })))
      .toBe('37% · 12 h HLTB · 3.2 h played')
  })
  it('uses one decimal under 10 h', () => {
    expect(metaLine(g({ hltb_hours: 4.25, playtime_minutes: 0 }))).toBe('50% · 4.3 h HLTB')
  })
  it('says so without achievements, HLTB or playtime', () => {
    expect(metaLine(g({ achievements_total: 0, hltb_hours: null, playtime_minutes: 0 }))).toBe('No achievements')
  })
})
