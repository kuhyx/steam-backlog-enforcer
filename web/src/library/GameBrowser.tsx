import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { LibraryGame } from '../api/contract'
import { q } from '../api/queries'
import { ErrorNotice, Loading } from '../ui/Notice'
import { buildIndex, search } from './fuzzy'
import { GameCard } from './GameCard'
import { SearchBox } from './SearchBox'
import { filterGames, NO_FILTERS, SORTS, sortGames, type Filters, type SortKey } from './view'

const SUGGESTIONS = 8

/** Pick mode: only `appIds` are selectable; the caller's button submits. */
export interface PickMode {
  appIds: ReadonlySet<number>
  selected: number | null
  onSelect: (appId: number) => void
}

const FILTER_LABELS: [keyof Filters, string][] = [
  ['hideCompleted', 'Hide completed'],
  ['installedOnly', 'Installed only'],
  ['pickableOnly', 'Pickable only'],
]

/** Grid columns as laid out right now (for ↑/↓ moving one row). */
function columns(grid: HTMLElement): number {
  return Math.max(1, getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length)
}

/**
 * Every owned game as a cover grid: fuzzy search with suggestions, sort,
 * filters. The grid is one tab stop; arrows, PageUp/PageDown and Home/End
 * move between cards (roving tabindex).
 */
export function GameBrowser({ pick }: { pick?: PickMode }) {
  const { data, error } = useQuery(q.library)
  const games = useMemo(() => data?.games ?? [], [data])
  const index = useMemo(() => buildIndex(games), [games])
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('name')
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [active, setActive] = useState(0)
  const [focusId, setFocusId] = useState<number | null>(null)
  const grid = useRef<HTMLDivElement>(null)
  const deferred = useDeferredValue(query)

  const reason = (g: LibraryGame): string | null =>
    pick ? (pick.appIds.has(g.app_id) ? null : (g.ineligible_reason ?? 'Not offered here')) : g.ineligible_reason
  const filtered = filterGames(games, filters, (g) => reason(g) === null)
  const visible = deferred.trim() ? search(filtered, index, deferred) : sortGames(filtered, sort)
  const suggestions = query.trim() ? search(filtered, index, query).slice(0, SUGGESTIONS) : []
  const current = Math.min(active, Math.max(0, visible.length - 1))

  useEffect(() => {
    if (focusId === null) return
    const card = grid.current?.querySelector<HTMLElement>(`[data-app-id="${focusId}"]`)
    if (!card) return
    setActive(Number(card.dataset.index))
    card.focus()
    setFocusId(null)
  }, [focusId, visible])

  const choose = (g: LibraryGame) => {
    if (pick && reason(g) === null) pick.onSelect(g.app_id)
    setFocusId(g.app_id)
  }

  const onGridKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const cols = columns(e.currentTarget)
    const page = cols * 3
    const moves: Record<string, number> = {
      ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols,
      PageDown: page, PageUp: -page, Home: -Infinity, End: Infinity,
    }
    if (!(e.key in moves) || visible.length === 0) return
    e.preventDefault()
    const next = Math.min(visible.length - 1, Math.max(0, current + moves[e.key]))
    setFocusId(visible[next].app_id)
  }

  return (
    <div className="lib">
      <div className="lib-toolbar">
        <SearchBox value={query} onChange={setQuery} suggestions={suggestions} reason={reason} onChoose={choose} />
        <label className="lib-sort">
          <span className="field-label">Sort</span>
          <select className="input" value={sort} disabled={deferred.trim() !== ''} onChange={(e) => setSort(e.target.value as SortKey)}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </label>
        <fieldset className="lib-filters">
          <legend className="sr-only">Filters</legend>
          {FILTER_LABELS.map(([key, label]) => (
            <label key={key} className="check">
              <input type="checkbox" checked={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.checked })} />
              {label}
            </label>
          ))}
        </fieldset>
        <span className="muted lib-count" aria-live="polite">
          {data && `${visible.length} of ${games.length} games${deferred.trim() ? ' · by relevance' : ''}`}
        </span>
      </div>
      {error && <ErrorNotice error={error} />}
      {!data && !error && <Loading what="your library" />}
      {data && visible.length === 0 && <p className="muted">No game matches.</p>}
      <div ref={grid} className="game-grid" role="group" aria-label="Games" onKeyDown={onGridKey}>
        {visible.map((g, i) => (
          <GameCard
            key={g.app_id}
            game={g}
            index={i}
            reason={reason(g)}
            selected={pick?.selected === g.app_id}
            focusable={i === current}
            pickMode={pick !== undefined}
            onActivate={
              pick
                ? () => {
                    setActive(i)
                    // Select only: assigning can uninstall other games, so
                    // it takes the explicit "Pick …" button, never a double-click.
                    if (reason(g) === null) pick.onSelect(g.app_id)
                  }
                : () => setActive(i)
            }
          />
        ))}
      </div>
    </div>
  )
}
