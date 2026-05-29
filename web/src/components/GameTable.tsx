import { useMemo, useState } from 'react'
import type { GameRow } from '../estimate'
import { fmtHoursPrecise, fmtPlaytime } from '../format'
import { tierLabel } from '../protondb'

interface Props {
  rows: GameRow[]
  search: string
  onSearch: (value: string) => void
  onToggleExclude: (appId: number) => void
}

type SortKey =
  | 'name'
  | 'completion'
  | 'playtime'
  | 'rush'
  | 'leisure'
  | 'worst'
  | 'count_comp'
  | 'proton'

const DISPLAY_CAP = 300

const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: 'name', label: 'Game', numeric: false },
  { key: 'completion', label: '%', numeric: true },
  { key: 'playtime', label: 'Played', numeric: true },
  { key: 'rush', label: 'Rush', numeric: true },
  { key: 'leisure', label: 'Leisure', numeric: true },
  { key: 'worst', label: 'Worst', numeric: true },
  { key: 'count_comp', label: 'HLTB n', numeric: true },
  { key: 'proton', label: 'ProtonDB', numeric: true },
]

function sortValue(row: GameRow, key: SortKey): number | string {
  const g = row.game
  switch (key) {
    case 'name':
      return g.name.toLowerCase()
    case 'completion':
      return g.completion_pct
    case 'playtime':
      return g.playtime_minutes
    case 'rush':
      return row.rush
    case 'leisure':
      return row.leisure
    case 'worst':
      return row.worst
    case 'count_comp':
      return g.count_comp
    case 'proton':
      return g.protondb_score
  }
}

function hltbUrl(game: GameRow['game']): string {
  if (game.hltb_game_id > 0) {
    return `https://howlongtobeat.com/game/${game.hltb_game_id}`
  }
  return `https://howlongtobeat.com/?q=${encodeURIComponent(game.name)}`
}

export function GameTable({ rows, search, onSearch, onToggleExclude }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('leisure')
  const [asc, setAsc] = useState(true)

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? rows.filter((r) => r.game.name.toLowerCase().includes(q))
      : rows
    const sorted = [...filtered].sort((a, b) => {
      const va = sortValue(a, sortKey)
      const vb = sortValue(b, sortKey)
      const cmp = va < vb ? -1 : va > vb ? 1 : 0
      return asc ? cmp : -cmp
    })
    return sorted
  }, [rows, search, sortKey, asc])

  const onHeader = (key: SortKey) => {
    if (key === sortKey) setAsc(!asc)
    else {
      setSortKey(key)
      setAsc(key === 'name')
    }
  }

  const shown = visible.slice(0, DISPLAY_CAP)

  return (
    <div className="table-wrap">
      <div className="table-head">
        <h2>Games ({visible.length})</h2>
        <input
          type="search"
          placeholder="Search games…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={c.numeric ? 'num clickable' : 'clickable'}
                  onClick={() => onHeader(c.key)}
                >
                  {c.label}
                  {sortKey === c.key ? (asc ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
              <th>Keep</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.game.app_id} className={r.excluded ? 'excluded' : ''}>
                <td className="name">
                  <a href={hltbUrl(r.game)} target="_blank" rel="noreferrer">
                    {r.game.name}
                  </a>
                  {r.noData && <span className="badge">no data</span>}
                </td>
                <td className="num">{r.game.completion_pct.toFixed(0)}</td>
                <td className="num">{fmtPlaytime(r.game.playtime_minutes)}</td>
                <td className="num">{fmtHoursPrecise(r.rush)}</td>
                <td className="num">{fmtHoursPrecise(r.leisure)}</td>
                <td className="num">{fmtHoursPrecise(r.worst)}</td>
                <td className="num">{r.game.count_comp}</td>
                <td className="num proton">
                  {tierLabel(r.game.protondb_tier, r.game.protondb_trending_tier)}
                </td>
                <td className="num">
                  <input
                    type="checkbox"
                    checked={!r.excluded}
                    onChange={() => onToggleExclude(r.game.app_id)}
                    aria-label={r.excluded ? 'Re-include' : 'Exclude'}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visible.length > DISPLAY_CAP && (
        <p className="hint">
          Showing first {DISPLAY_CAP} of {visible.length}. Use search to narrow.
        </p>
      )}
    </div>
  )
}
