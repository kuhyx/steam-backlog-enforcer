import { describe, expect, it } from 'vitest'
import { applyFilters, type GameRow } from '../../estimate'
import { buildIndex } from '../../library/fuzzy'
import { makeDataset, makeFilters, makeGame } from '../../test/factories'
import type { WebGame } from '../../types'
import { COLUMNS, compareValues, defaultTable, optionsFor, readTable, toggleSort, visibleRows, writeTable, type ColumnKey, type TableState } from './tableState'

const GAMES: WebGame[] = [
  makeGame({ app_id: 1, name: 'Hollow Knight', completion_pct: 40, playtime_minutes: 600, rush_hours: 30, leisure_hours: 50, worst_hours: 70, count_comp: 90, protondb_tier: 'platinum', protondb_trending_tier: 'platinum', protondb_score: 0.9 }),
  makeGame({ app_id: 2, name: 'Celeste', completion_pct: 10, playtime_minutes: 0, rush_hours: 10, leisure_hours: 20, worst_hours: 25, count_comp: 40, protondb_tier: 'gold', protondb_trending_tier: 'silver', protondb_score: 0.5 }),
  makeGame({ app_id: 3, name: 'Hades', completion_pct: 70, playtime_minutes: 120, rush_hours: -1, leisure_hours: -1, worst_hours: -1, count_comp: 20, protondb_tier: 'gold', protondb_trending_tier: 'gold', protondb_score: 0.7 }),
]

function rows(excluded: number[] = []): GameRow[] {
  return applyFilters(makeDataset(GAMES), makeFilters({ includeNoData: true, fallbackHours: 15, excluded: new Set(excluded) })).rows
}
const index = buildIndex(GAMES)
const names = (s: TableState, query = '', r = rows()) => visibleRows(r, s, query, index).map((x) => x.game.name)
const withFilters = (f: Record<string, string>, over: Partial<TableState> = {}): TableState => ({
  ...defaultTable(),
  ...over,
  filters: new Map(Object.entries(f)),
})

describe('toggleSort', () => {
  it('flips the direction on the same column, names start A→Z and numbers high→low', () => {
    const s = defaultTable()
    expect(toggleSort(s, 'leisure')).toMatchObject({ sort: 'leisure', asc: false })
    expect(toggleSort(s, 'name')).toMatchObject({ sort: 'name', asc: true })
    expect(toggleSort(s, 'rush')).toMatchObject({ sort: 'rush', asc: false })
  })
})

describe('visibleRows', () => {
  it('sorts by leisure ascending by default, fallback hours counting as data', () => {
    expect(names(defaultTable())).toEqual(['Hades', 'Celeste', 'Hollow Knight'])
  })

  it('sorts every column both ways and changes the order', () => {
    const r = applyFilters(makeDataset(GAMES), makeFilters({ excluded: new Set([2]) })).rows
    for (const c of COLUMNS) {
      const asc = names({ ...defaultTable(), sort: c.key, asc: true }, '', r)
      const desc = names({ ...defaultTable(), sort: c.key, asc: false }, '', r)
      expect(asc, c.key).toHaveLength(3)
      expect(desc, c.key).not.toEqual(asc)
    }
  })

  it('keeps games with no data last whichever way the column runs', () => {
    const more = [...GAMES, makeGame({ app_id: 4, name: 'Abzu', rush_hours: -1, leisure_hours: -1, worst_hours: -1 })]
    const r = applyFilters(makeDataset(more), makeFilters()).rows
    expect(names({ ...defaultTable(), sort: 'rush', asc: true }, '', r)).toEqual(['Celeste', 'Hollow Knight', 'Abzu', 'Hades'])
    expect(names({ ...defaultTable(), sort: 'rush', asc: false }, '', r)).toEqual(['Hollow Knight', 'Celeste', 'Abzu', 'Hades'])
  })

  it('breaks ties by name', () => {
    const tied = rows().map((x) => ({ ...x, game: { ...x.game, completion_pct: 5 } }))
    expect(names({ ...defaultTable(), sort: 'completion' }, '', tied)).toEqual(['Celeste', 'Hades', 'Hollow Knight'])
  })

  it('filters by the fuzzy search, typos and app ids included', () => {
    expect(names(defaultTable(), 'holow knigt')).toEqual(['Hollow Knight'])
    expect(names(defaultTable(), '2')).toEqual(['Celeste'])
    expect(names(defaultTable(), '   ')).toHaveLength(3)
  })

  it('filters a text column by substring', () => {
    expect(names(withFilters({ name: ' HA ' }))).toEqual(['Hades'])
  })

  it('filters a range by min, max or both; a blank or junk bound is ignored', () => {
    expect(names(withFilters({ 'completion.min': '20' }))).toEqual(['Hades', 'Hollow Knight'])
    expect(names(withFilters({ 'playtime.max': '2' }))).toEqual(['Hades', 'Celeste'])
    expect(names(withFilters({ 'count_comp.min': '30', 'count_comp.max': '50' }))).toEqual(['Celeste'])
    expect(names(withFilters({ 'rush.min': ' ', 'rush.max': 'abc' }))).toHaveLength(3)
  })

  it('drops rows with no data once a range is set on that column', () => {
    const r = applyFilters(makeDataset(GAMES), makeFilters()).rows
    expect(names(withFilters({ 'worst.max': '1000' }), '', r)).toEqual(['Celeste', 'Hollow Knight'])
  })

  it('filters select columns by the exact option, case-insensitively', () => {
    expect(names(withFilters({ proton: 'GOLD' }))).toEqual(['Hades'])
    expect(names(withFilters({ proton: 'gold / silver' }))).toEqual(['Celeste'])
    expect(names(withFilters({ keep: 'excluded' }), '', rows([3]))).toEqual(['Hades'])
    expect(names(withFilters({ keep: 'kept' }), '', rows([3]))).toEqual(['Celeste', 'Hollow Knight'])
  })
})

describe('compareValues', () => {
  it('puts missing values last both ways and compares strings and numbers', () => {
    expect(compareValues(null, 1, true)).toBe(1)
    expect(compareValues(null, 1, false)).toBe(1)
    expect(compareValues(1, null, false)).toBe(-1)
    expect(compareValues(null, null, true)).toBe(0)
    expect(compareValues('a', 'b', true)).toBeLessThan(0)
    expect(compareValues(1, 2, false)).toBe(1)
  })
})

describe('optionsFor', () => {
  const col = (key: ColumnKey) => COLUMNS.find((c) => c.key === key) ?? COLUMNS[0]
  it('lists the distinct ProtonDB labels, plus a restored value', () => {
    expect(optionsFor(col('proton'), rows())).toEqual(['gold', 'gold / silver', 'platinum'])
    expect(optionsFor(col('proton'), rows(), 'borked')).toEqual(['borked', 'gold', 'gold / silver', 'platinum'])
  })
  it('offers kept / excluded for the keep column', () => {
    expect(optionsFor(col('keep'), [])).toEqual(['kept', 'excluded'])
  })
})

describe('hash form', () => {
  it('writes nothing for the default state', () => {
    const p = new URLSearchParams()
    writeTable(defaultTable(), p)
    expect(p.toString()).toBe('')
  })

  it('round-trips sort, text, select and range filters', () => {
    const s = withFilters(
      { name: 'hol', proton: 'gold', 'rush.min': '5', 'rush.max': ' ', 'worst.max': '40', 'completion.min': ' ' },
      { sort: 'rush', asc: false },
    )
    const p = new URLSearchParams()
    writeTable(s, p)
    expect(p.toString()).toBe('sort=rush&dir=desc&f.name=hol&f.rush=5..&f.worst=..40&f.proton=gold')
    const back = readTable(new URLSearchParams(p.toString()))
    expect(back.sort).toBe('rush')
    expect(back.asc).toBe(false)
    expect([...back.filters]).toEqual([
      ['name', 'hol'],
      ['rush.min', '5'],
      ['worst.max', '40'],
      ['proton', 'gold'],
    ])
  })

  it('writes a non-default direction on the default column, reads asc unless told desc', () => {
    const p = new URLSearchParams()
    writeTable({ ...defaultTable(), asc: false }, p)
    expect(p.toString()).toBe('sort=leisure&dir=desc')
    expect(readTable(new URLSearchParams('sort=name')).asc).toBe(true)
  })

  it('ignores an unknown sort column and a bare range', () => {
    const s = readTable(new URLSearchParams('sort=bogus&dir=desc&f.rush=..'))
    expect(s).toEqual(defaultTable())
  })
})
