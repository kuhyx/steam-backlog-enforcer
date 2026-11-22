import { describe, expect, it } from 'vitest'
import type { CompatRow } from '../api/contract'
import {
  COMPAT_COLUMNS,
  compatOptions,
  defaultCompat,
  readCompat,
  toggleCompatSort,
  toolLabel,
  visibleCompat,
  whyText,
  writeCompat,
  type CompatState,
} from './compatState'
import { makeCompatRow } from '../test/fixtures'
import { buildIndex } from './fuzzy'

const TOOL = 'proton-cachyos-native'

// Real shape: most rows keep Valve's default (duplicates), one kept tool,
// one already mapped, one missing from the app cache, long reason lists.
const ROWS: CompatRow[] = [
  makeCompatRow({ app_id: 1245620, name: 'Elden Ring', decided: null, map: false, changes: false, reasons: ['anti-cheat'] }),
  makeCompatRow({ app_id: 70, name: 'Half-Life', decided: null, map: false, changes: false, reasons: ['native', 'not Windows-only'] }),
  makeCompatRow({ app_id: 292030, name: 'The Witcher 3', current: null }),
  makeCompatRow({ app_id: 1091500, name: 'Cyberpunk 2077', current: 'GE-Proton10', priority: '250', decided: 'GE-Proton10', changes: false, note: 'kept: already mapped to GE-Proton10 (priority 250)' }),
  makeCompatRow({ app_id: 413150, name: 'Stardew Valley', current: TOOL, priority: '250', changes: false, note: 'already mapped' }),
  makeCompatRow({ app_id: 4000, name: 'Garry', decided: null, map: false, changes: false, cached: false, reasons: ["not in Steam's app cache"] }),
]

const names = (s: CompatState) => visibleCompat(ROWS, s, buildIndex(ROWS)).map((r) => r.name)
const state = (over: Partial<CompatState> = {}): CompatState => ({ ...defaultCompat(), ...over })

describe('compat columns', () => {
  it('has the six data columns in order', () => {
    expect(COMPAT_COLUMNS.map((c) => c.key)).toEqual(['name', 'app_id', 'current', 'decided', 'why', 'changes'])
  })

  it('gives every column a text form, app ids as digits', () => {
    expect(COMPAT_COLUMNS.map((c) => c.text(ROWS[2]))).toEqual(['The Witcher 3', '292030', 'Valve default', TOOL, '', 'changes'])
  })

  it('labels a missing tool as Valve default and joins reasons, else the note', () => {
    expect(toolLabel(null)).toBe('Valve default')
    expect(toolLabel(TOOL)).toBe(TOOL)
    expect(whyText(ROWS[1])).toBe('native, not Windows-only')
    expect(whyText(ROWS[4])).toBe('already mapped')
    expect(whyText(ROWS[2])).toBe('')
  })
})

describe('visibleCompat', () => {
  it('puts the games that change first by default', () => {
    expect(names(state())[0]).toBe('The Witcher 3')
  })

  it('sorts names A→Z and reverses on a second click', () => {
    const once = toggleCompatSort(state(), 'name')
    expect(names(once)).toEqual(['Cyberpunk 2077', 'Elden Ring', 'Garry', 'Half-Life', 'Stardew Valley', 'The Witcher 3'])
    expect(names(toggleCompatSort(once, 'name'))).toEqual([...names(once)].reverse())
  })

  it('reverses ties too, so a column of equal values still reorders', () => {
    const asc = state({ sort: 'current', asc: true })
    const desc = state({ sort: 'current', asc: false })
    expect(names(asc)).not.toEqual(names(desc))
  })

  it('breaks a name tie by app id, in the sort direction', () => {
    const twins = [makeCompatRow({ app_id: 2, name: 'Twin' }), makeCompatRow({ app_id: 1, name: 'Twin' })]
    const ids = (asc: boolean) => visibleCompat(twins, state({ sort: 'name', asc }), buildIndex(twins)).map((r) => r.app_id)
    expect(ids(true)).toEqual([1, 2])
    expect(ids(false)).toEqual([2, 1])
  })

  it('sorts app ids numerically, high first on the first click', () => {
    const s = toggleCompatSort(state(), 'app_id')
    expect(visibleCompat(ROWS, s, buildIndex(ROWS)).map((r) => r.app_id)[0]).toBe(1245620)
  })

  it('filters by a select column value', () => {
    const s = state({ filters: new Map([['decided', 'Valve default']]) })
    expect(names(s).sort()).toEqual(['Elden Ring', 'Garry', 'Half-Life'])
    const changing = state({ filters: new Map([['changes', 'changes']]) })
    expect(names(changing)).toEqual(['The Witcher 3'])
  })

  it('filters text columns by substring and app ids by range', () => {
    expect(names(state({ filters: new Map([['why', 'anti']]) }))).toEqual(['Elden Ring'])
    expect(names(state({ filters: new Map([['app_id.min', '1000000']]) })).sort()).toEqual(['Cyberpunk 2077', 'Elden Ring'])
    expect(names(state({ filters: new Map([['app_id.max', '100']]) }))).toEqual(['Half-Life'])
    expect(names(state({ filters: new Map([['name', 'ring']]) }))).toEqual(['Elden Ring'])
  })

  it('fuzzy-searches names with typos and roman numerals', () => {
    expect(names(state({ query: 'wicher iii' }))).toEqual(['The Witcher 3'])
  })
})

describe('compat options and hash', () => {
  it('lists distinct options, plus a restored value', () => {
    const decided = COMPAT_COLUMNS.find((c) => c.key === 'decided')
    if (!decided) throw new Error('no decided column')
    expect(compatOptions(decided, ROWS)).toEqual(['GE-Proton10', TOOL, 'Valve default'])
    expect(compatOptions(decided, ROWS, 'gone')).toContain('gone')
    const changes = COMPAT_COLUMNS.find((c) => c.key === 'changes')
    if (!changes) throw new Error('no changes column')
    expect(compatOptions(changes, [])).toEqual(['changes', 'same'])
  })

  it('round-trips through c.-prefixed keys and leaves other keys alone', () => {
    const s = state({ sort: 'name', asc: true, query: 'ring', filters: new Map([['why', 'anti'], ['app_id.min', '5']]) })
    const p = new URLSearchParams('q=hollow&sort=recent&view=compat')
    writeCompat(s, p)
    expect(p.get('q')).toBe('hollow')
    expect(p.get('sort')).toBe('recent')
    expect(p.get('c.sort')).toBe('name')
    expect(p.get('c.f.app_id')).toBe('5..')
    const back = readCompat(p)
    expect(back).toEqual(s)
  })

  it('writes nothing for the default state and drops stale keys', () => {
    const p = new URLSearchParams('c.sort=name&c.dir=asc&c.q=x&c.f.why=y')
    writeCompat(defaultCompat(), p)
    expect(p.toString()).toBe('')
  })

  it('ignores an unknown sort column', () => {
    expect(readCompat(new URLSearchParams('c.sort=nope')).sort).toBe(defaultCompat().sort)
    expect(readCompat(new URLSearchParams('c.sort=name&c.dir=desc')).asc).toBe(false)
    expect(readCompat(new URLSearchParams('c.f.app_id=..9')).filters.get('app_id.max')).toBe('9')
  })
})
