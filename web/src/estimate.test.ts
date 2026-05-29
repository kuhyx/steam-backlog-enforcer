import { describe, expect, it } from 'vitest'
import { applyFilters, basisTotal, etaDays, paceDays } from './estimate'
import { makeDataset, makeFilters, makeGame } from './test/factories'

describe('applyFilters — totals and parity', () => {
  it('sums each metric independently over qualifying games', () => {
    const r = applyFilters(
      makeDataset([
        makeGame({ app_id: 1, rush_hours: 10, leisure_hours: 25, worst_hours: 30 }),
        makeGame({ app_id: 2, rush_hours: 5, leisure_hours: 8, worst_hours: 9 }),
      ]),
      makeFilters(),
    )
    expect(r.remainingGames).toBe(2)
    expect(r.rushTotal).toBe(15)
    expect(r.leisureTotal).toBe(33)
    expect(r.worstTotal).toBe(39)
  })

  it('omits a missing metric from its total (partial data)', () => {
    const r = applyFilters(
      makeDataset([makeGame({ rush_hours: -1, leisure_hours: 20, worst_hours: 25 })]),
      makeFilters(),
    )
    expect(r.rushTotal).toBe(0)
    expect(r.leisureTotal).toBe(20)
  })

  it('skips non-positive leisure and worst when summing (rush basis)', () => {
    const r = applyFilters(
      makeDataset([makeGame({ rush_hours: 10, leisure_hours: -1, worst_hours: -1 })]),
      makeFilters({ basis: 'rush' }),
    )
    expect(r.remainingGames).toBe(1)
    expect(r.rushTotal).toBe(10)
    expect(r.leisureTotal).toBe(0)
    expect(r.worstTotal).toBe(0)
  })
})

describe('applyFilters — threshold filters', () => {
  it('excludes low-confidence games', () => {
    const r = applyFilters(makeDataset([makeGame({ count_comp: 0 })]), makeFilters())
    expect(r.remainingGames).toBe(0)
  })

  it('rejects unplayable games in playable mode', () => {
    const r = applyFilters(
      makeDataset([
        makeGame({ protondb_tier: 'borked', protondb_trending_tier: 'borked' }),
      ]),
      makeFilters(),
    )
    expect(r.remainingGames).toBe(0)
  })

  it('honours the min-tier ProtonDB mode', () => {
    const g = makeGame({ protondb_tier: 'silver', protondb_trending_tier: 'silver' })
    const r = applyFilters(
      makeDataset([g]),
      makeFilters({ protonMode: 'minTier', protonMinTier: 'silver' }),
    )
    expect(r.remainingGames).toBe(1)
  })

  it('filters by playtime (started vs untouched)', () => {
    const games = [
      makeGame({ app_id: 1, playtime_minutes: 0 }),
      makeGame({ app_id: 2, playtime_minutes: 30 }),
    ]
    expect(
      applyFilters(
        makeDataset(games),
        makeFilters({ playtimeMode: 'started' }),
      ).included.map((r) => r.game.app_id),
    ).toEqual([2])
    expect(
      applyFilters(
        makeDataset(games),
        makeFilters({ playtimeMode: 'untouched' }),
      ).included.map((r) => r.game.app_id),
    ).toEqual([1])
  })

  it('applies the max time-per-game cap', () => {
    const r = applyFilters(
      makeDataset([
        makeGame({ app_id: 1, leisure_hours: 10 }),
        makeGame({ app_id: 2, leisure_hours: 80 }),
      ]),
      makeFilters({ maxHoursPerGame: 50 }),
    )
    expect(r.included.map((x) => x.game.app_id)).toEqual([1])
  })
})

describe('applyFilters — no-data handling', () => {
  const noData = makeGame({ rush_hours: -1, leisure_hours: -1, worst_hours: -1 })

  it('excludes no-data games by default', () => {
    expect(applyFilters(makeDataset([noData]), makeFilters()).remainingGames).toBe(0)
  })

  it('includes no-data games with the fallback applied to every metric', () => {
    const r = applyFilters(
      makeDataset([noData]),
      makeFilters({ includeNoData: true, fallbackHours: 12 }),
    )
    expect(r.remainingGames).toBe(1)
    expect(r.rushTotal).toBe(12)
    expect(r.leisureTotal).toBe(12)
    expect(r.worstTotal).toBe(12)
  })
})

describe('applyFilters — exclusions', () => {
  it('keeps passesFilters true but drops a manually excluded game from totals', () => {
    const r = applyFilters(
      makeDataset([makeGame({ app_id: 1 })]),
      makeFilters({ excluded: new Set([1]) }),
    )
    expect(r.remainingGames).toBe(0)
    expect(r.rows[0].passesFilters).toBe(true)
    expect(r.rows[0].excluded).toBe(true)
    expect(r.rows[0].included).toBe(false)
  })
})

describe('basis length proxy', () => {
  it('uses leisure as the length proxy for the pace basis', () => {
    const r = applyFilters(
      makeDataset([makeGame({ leisure_hours: 30 })]),
      makeFilters({ basis: 'pace' }),
    )
    expect(r.included[0].lengthHours).toBe(30)
  })

  it('uses rush hours as length for the rush basis', () => {
    const r = applyFilters(
      makeDataset([makeGame({ rush_hours: 7 })]),
      makeFilters({ basis: 'rush' }),
    )
    expect(r.included[0].lengthHours).toBe(7)
  })

  it('uses worst hours as length for the worst basis', () => {
    const r = applyFilters(
      makeDataset([makeGame({ worst_hours: 99 })]),
      makeFilters({ basis: 'worst', maxHoursPerGame: 0 }),
    )
    expect(r.included[0].lengthHours).toBe(99)
  })
})

describe('etaDays / paceDays / basisTotal', () => {
  it('etaDays floors and guards zero inputs', () => {
    expect(etaDays(40, 4)).toBe(10)
    expect(etaDays(0, 4)).toBeNull()
    expect(etaDays(40, 0)).toBeNull()
  })

  it('paceDays floors and guards zero inputs', () => {
    expect(paceDays(10, 0.5)).toBe(20)
    expect(paceDays(0, 1)).toBeNull()
    expect(paceDays(10, 0)).toBeNull()
  })

  it('basisTotal returns the right total or null for pace', () => {
    const r = applyFilters(makeDataset([makeGame()]), makeFilters())
    expect(basisTotal(r, 'rush')).toBe(r.rushTotal)
    expect(basisTotal(r, 'leisure')).toBe(r.leisureTotal)
    expect(basisTotal(r, 'worst')).toBe(r.worstTotal)
    expect(basisTotal(r, 'pace')).toBeNull()
  })
})
