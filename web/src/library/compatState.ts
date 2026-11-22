// The Proton map's columns, sort, per-column filters, fuzzy search and hash
// state, as pure functions so <compat-table> only wires inputs to them.
// Hash grammar (prefixed `c.`: the cover grid owns `q` and `sort` in the same
// hash): `c.sort=<col>&c.dir=asc|desc`, `c.q=<search>`, `c.f.<col>=text` for
// text/select columns and `c.f.app_id=min..max` (either side optional).

import type { CompatRow } from '../api/contract'
import { search, type Searchable } from './fuzzy'

export type CompatKey = 'name' | 'app_id' | 'current' | 'decided' | 'why' | 'changes'
export type CompatFilter = 'text' | 'range' | 'select'

export interface CompatColumn {
  key: CompatKey
  label: string
  numeric: boolean
  filter: CompatFilter
  /** Sort key (and the range filter's value). */
  value: (r: CompatRow) => number | string
  /** Select columns: the option a row belongs to; text columns: the searched text. */
  text: (r: CompatRow) => string
}

export const VALVE_DEFAULT = 'Valve default'

/** A tool as data: its name, or Valve's default when the game has none. */
export const toolLabel = (tool: string | null): string => tool ?? VALVE_DEFAULT

/** The reason column: the decision's reasons, else apply's note ('' = maps). */
export const whyText = (r: CompatRow): string => (r.reasons.length > 0 ? r.reasons.join(', ') : (r.note ?? ''))

const changeOption = (r: CompatRow) => (r.changes ? 'changes' : 'same')

export const COMPAT_COLUMNS: readonly CompatColumn[] = [
  { key: 'name', label: 'Game', numeric: false, filter: 'text', value: (r) => r.name.toLowerCase(), text: (r) => r.name },
  { key: 'app_id', label: 'App id', numeric: true, filter: 'range', value: (r) => r.app_id, text: (r) => String(r.app_id) },
  { key: 'current', label: 'Current tool', numeric: false, filter: 'select', value: (r) => toolLabel(r.current), text: (r) => toolLabel(r.current) },
  { key: 'decided', label: 'Decided tool', numeric: false, filter: 'select', value: (r) => toolLabel(r.decided), text: (r) => toolLabel(r.decided) },
  { key: 'why', label: 'Reason', numeric: false, filter: 'text', value: (r) => whyText(r), text: whyText },
  // 0 sorts first: ascending (the first click) lists the games that change on top.
  { key: 'changes', label: 'Changes', numeric: false, filter: 'select', value: (r) => (r.changes ? 0 : 1), text: changeOption },
]

const BY_KEY = Object.fromEntries(COMPAT_COLUMNS.map((c) => [c.key, c])) as Record<CompatKey, CompatColumn>

export interface CompatState {
  sort: CompatKey
  asc: boolean
  /** Raw filter values: `<col>` for text/select, `app_id.min` / `app_id.max`. */
  filters: Map<string, string>
  query: string
}

/** Games that change first: what an apply would do is the point of the view. */
export const defaultCompat = (): CompatState => ({ sort: 'changes', asc: true, filters: new Map(), query: '' })

/** Header click: flip the direction, or switch column (text A→Z, numbers high→low). */
export function toggleCompatSort(s: CompatState, key: CompatKey): CompatState {
  if (key === s.sort) return { ...s, asc: !s.asc }
  return { ...s, sort: key, asc: !BY_KEY[key].numeric }
}

const bound = (raw: string | undefined): number | null => {
  const t = raw?.trim() ?? ''
  const n = Number(t)
  return t === '' || !Number.isFinite(n) ? null : n
}

function passes(r: CompatRow, c: CompatColumn, filters: ReadonlyMap<string, string>): boolean {
  if (c.filter === 'range') {
    const min = bound(filters.get(`${c.key}.min`))
    const max = bound(filters.get(`${c.key}.max`))
    const v = c.value(r) as number
    return (min === null || v >= min) && (max === null || v <= max)
  }
  const want = (filters.get(c.key) ?? '').trim().toLowerCase()
  if (!want) return true
  const have = c.text(r).toLowerCase()
  return c.filter === 'select' ? have === want : have.includes(want)
}

const compare = (a: number | string, b: number | string): number =>
  typeof a === 'string' ? a.localeCompare(String(b)) : a - (b as number)

/**
 * Rows matching the fuzzy search and every column filter, in the state's
 * order. Ties fall back to name then app id IN THE SAME DIRECTION, so a
 * column whose values are all equal still reverses on its second click.
 */
export function visibleCompat(rows: readonly CompatRow[], s: CompatState, index: ReadonlyMap<number, Searchable>): CompatRow[] {
  const hits = s.query.trim() ? new Set(search(rows, index, s.query).map((r) => r.app_id)) : null
  const col = BY_KEY[s.sort]
  const sign = s.asc ? 1 : -1
  return rows
    .filter((r) => (hits === null || hits.has(r.app_id)) && COMPAT_COLUMNS.every((c) => passes(r, c, s.filters)))
    .sort((a, b) => sign * (compare(col.value(a), col.value(b)) || a.name.localeCompare(b.name) || a.app_id - b.app_id))
}

/** Distinct options of a select column across `rows`, plus `keep` (a restored value). */
export function compatOptions(c: CompatColumn, rows: readonly CompatRow[], keep = ''): string[] {
  if (c.key === 'changes') return ['changes', 'same']
  const opts = new Set(rows.map((r) => c.text(r)))
  if (keep) opts.add(keep)
  return [...opts].sort((a, b) => a.localeCompare(b))
}

const P = 'c.'

/** Write `s` into `p` under `c.` keys, dropping keys at their default. */
export function writeCompat(s: CompatState, p: URLSearchParams): void {
  for (const key of [...p.keys()]) if (key.startsWith(P)) p.delete(key)
  const d = defaultCompat()
  if (s.sort !== d.sort || s.asc !== d.asc) {
    p.set(`${P}sort`, s.sort)
    p.set(`${P}dir`, s.asc ? 'asc' : 'desc')
  }
  if (s.query.trim()) p.set(`${P}q`, s.query)
  for (const c of COMPAT_COLUMNS) {
    if (c.filter === 'range') {
      const min = s.filters.get(`${c.key}.min`)?.trim() ?? ''
      const max = s.filters.get(`${c.key}.max`)?.trim() ?? ''
      if (min || max) p.set(`${P}f.${c.key}`, `${min}..${max}`)
    } else {
      const v = s.filters.get(c.key) ?? ''
      if (v) p.set(`${P}f.${c.key}`, v)
    }
  }
}

export function readCompat(p: URLSearchParams): CompatState {
  const s = defaultCompat()
  const sort = COMPAT_COLUMNS.find((c) => c.key === p.get(`${P}sort`))
  if (sort) {
    s.sort = sort.key
    s.asc = p.get(`${P}dir`) !== 'desc'
  }
  s.query = p.get(`${P}q`) ?? ''
  for (const c of COMPAT_COLUMNS) {
    const raw = p.get(`${P}f.${c.key}`)
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
