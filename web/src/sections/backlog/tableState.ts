// The game table's columns, sort and per-column filters (was GameTable's
// sort state), as pure functions so the element only wires inputs to them.
// Hash grammar: `sort=<col>&dir=asc|desc`, `f.<col>=text` for text/select
// columns and `f.<col>=min..max` (either side optional) for numeric ones.

import type { GameRow } from '../../estimate'
import { search, type Searchable } from '../../library/fuzzy'
import { tierLabel } from '../../protondb'

export type ColumnKey = 'name' | 'completion' | 'playtime' | 'rush' | 'leisure' | 'worst' | 'count_comp' | 'proton' | 'keep'
export type FilterKind = 'text' | 'range' | 'select'

export interface Column {
  key: ColumnKey
  label: string
  numeric: boolean
  filter: FilterKind
  /** Sort key and range-filter value; null = no data (sorts last, fails any bound). */
  value: (r: GameRow) => number | string | null
  /** Select columns: the option a row belongs to. */
  option?: (r: GameRow) => string
}

const hours = (h: number) => (h > 0 ? h : null)
const keepOption = (r: GameRow) => (r.excluded ? 'excluded' : 'kept')

export const COLUMNS: readonly Column[] = [
  { key: 'name', label: 'Game', numeric: false, filter: 'text', value: (r) => r.game.name.toLowerCase() },
  { key: 'completion', label: '%', numeric: true, filter: 'range', value: (r) => r.game.completion_pct },
  { key: 'playtime', label: 'Played', numeric: true, filter: 'range', value: (r) => r.game.playtime_minutes / 60 },
  { key: 'rush', label: 'Rush', numeric: true, filter: 'range', value: (r) => hours(r.rush) },
  { key: 'leisure', label: 'Leisure', numeric: true, filter: 'range', value: (r) => hours(r.leisure) },
  { key: 'worst', label: 'Worst', numeric: true, filter: 'range', value: (r) => hours(r.worst) },
  { key: 'count_comp', label: 'HLTB n', numeric: true, filter: 'range', value: (r) => r.game.count_comp },
  {
    key: 'proton',
    label: 'ProtonDB',
    numeric: true,
    filter: 'select',
    value: (r) => r.game.protondb_score,
    option: (r) => tierLabel(r.game.protondb_tier, r.game.protondb_trending_tier),
  },
  { key: 'keep', label: 'Keep', numeric: true, filter: 'select', value: (r) => (r.excluded ? 1 : 0), option: keepOption },
]

const BY_KEY = Object.fromEntries(COLUMNS.map((c) => [c.key, c])) as Record<ColumnKey, Column>

export interface TableState {
  sort: ColumnKey
  asc: boolean
  /** Raw filter input values: `<col>` for text/select, `<col>.min` / `<col>.max` for ranges. */
  filters: Map<string, string>
}

export const defaultTable = (): TableState => ({ sort: 'leisure', asc: true, filters: new Map() })

/** Header click: flip the direction, or switch column (names A→Z, numbers high→low). */
export function toggleSort(s: TableState, key: ColumnKey): TableState {
  if (key === s.sort) return { ...s, asc: !s.asc }
  return { ...s, sort: key, asc: key === 'name' }
}

const bound = (raw: string | undefined): number | null => {
  const t = raw?.trim() ?? ''
  const n = Number(t)
  return t === '' || !Number.isFinite(n) ? null : n
}

function passes(r: GameRow, c: Column, filters: ReadonlyMap<string, string>): boolean {
  if (c.filter === 'range') {
    const min = bound(filters.get(`${c.key}.min`))
    const max = bound(filters.get(`${c.key}.max`))
    if (min === null && max === null) return true
    const v = c.value(r) as number | null
    return v !== null && (min === null || v >= min) && (max === null || v <= max)
  }
  const want = (filters.get(c.key) ?? '').trim().toLowerCase()
  if (!want) return true
  if (c.option) return c.option(r).toLowerCase() === want
  return r.game.name.toLowerCase().includes(want)
}

/** Column order for two values, missing ones last in either direction. */
export function compareValues(a: number | string | null, b: number | string | null, asc: boolean): number {
  if (a === null || b === null) return Number(a === null) - Number(b === null)
  const cmp = typeof a === 'string' ? a.localeCompare(String(b)) : a - (b as number)
  return asc ? cmp : -cmp
}

/**
 * Rows matching the fuzzy `query` (src/library/fuzzy: typos, roman numerals,
 * app ids) and every column filter, in the state's sort order.
 */
export function visibleRows(
  rows: readonly GameRow[],
  s: TableState,
  query: string,
  index: ReadonlyMap<number, Searchable>,
): GameRow[] {
  const hits = query.trim()
    ? new Set(search(rows.map((r) => r.game), index, query).map((g) => g.app_id))
    : null
  const col = BY_KEY[s.sort]
  return rows
    .filter((r) => (hits === null || hits.has(r.game.app_id)) && COLUMNS.every((c) => passes(r, c, s.filters)))
    .sort((a, b) => compareValues(col.value(a), col.value(b), s.asc) || a.game.name.localeCompare(b.game.name))
}

/** Distinct options of a select column across `rows`, plus `keep` (a restored value). */
export function optionsFor(c: Column, rows: readonly GameRow[], keep = ''): string[] {
  if (c.key === 'keep') return ['kept', 'excluded']
  const opts = new Set(rows.map((r) => (c.option as (r: GameRow) => string)(r)))
  if (keep) opts.add(keep)
  return [...opts].sort()
}

export function writeTable(s: TableState, p: URLSearchParams): void {
  const d = defaultTable()
  if (s.sort !== d.sort || s.asc !== d.asc) {
    p.set('sort', s.sort)
    p.set('dir', s.asc ? 'asc' : 'desc')
  }
  for (const c of COLUMNS) {
    if (c.filter === 'range') {
      const min = s.filters.get(`${c.key}.min`)?.trim() ?? ''
      const max = s.filters.get(`${c.key}.max`)?.trim() ?? ''
      if (min || max) p.set(`f.${c.key}`, `${min}..${max}`)
    } else {
      const v = s.filters.get(c.key) ?? ''
      if (v) p.set(`f.${c.key}`, v)
    }
  }
}

export function readTable(p: URLSearchParams): TableState {
  const s = defaultTable()
  const sort = COLUMNS.find((c) => c.key === p.get('sort'))
  if (sort) {
    s.sort = sort.key
    s.asc = p.get('dir') !== 'desc'
  }
  for (const c of COLUMNS) {
    const raw = p.get(`f.${c.key}`)
    if (raw === null) continue
    if (c.filter === 'range') {
      const [min = '', max = ''] = raw.split('..')
      if (min) s.filters.set(`${c.key}.min`, min)
      if (max) s.filters.set(`${c.key}.max`, max)
    } else {
      s.filters.set(c.key, raw)
    }
  }
  return s
}
