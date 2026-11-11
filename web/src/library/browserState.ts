// What `<game-browser>` shows: the search, sort and filters. With
// `hash-state` (the Library page only) they live in the URL hash, so a
// reload restores them.

import { readHash } from './hashState'
import { NO_FILTERS, SORTS, type Filters, type SortKey } from './view'

/** Filter key, spoken checkbox label, its token in the hash's `f=` list, painted glyph. */
export const FILTERS: [keyof Filters, string, string, string][] = [
  ['hideCompleted', 'Hide completed', 'completed', '🙈🏆'],
  ['installedOnly', 'Installed only', 'installed', '💾'],
  ['pickableOnly', 'Pickable only', 'pickable', '🎯'],
]

export interface BrowserState {
  query: string
  sort: SortKey
  filters: Filters
}

const isSort = (s: string | null): s is SortKey => SORTS.some((o) => o.key === s)

/** Search, sort and filters from `#q=…&sort=…&f=…`; unknown values fall back to the defaults. */
export function stateFromHash(): BrowserState {
  const p = readHash()
  const sort = p.get('sort')
  const tokens = (p.get('f') ?? '').split(',')
  const filters = { ...NO_FILTERS }
  for (const [key, , token] of FILTERS) filters[key] = tokens.includes(token)
  return { query: p.get('q') ?? '', sort: isSort(sort) ? sort : 'name', filters }
}

/** The hash keys for `s`; defaults are dropped so a fresh view has no hash. */
export function stateToHash(s: BrowserState): Record<string, string | null> {
  return {
    q: s.query,
    sort: s.sort === 'name' ? null : s.sort,
    f: FILTERS.filter(([key]) => s.filters[key]).map(([, , token]) => token).join(','),
  }
}
