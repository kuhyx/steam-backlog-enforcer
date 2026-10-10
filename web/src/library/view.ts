// Sorting, filtering and labels for the library browser. Pure functions, so
// the grid component only wires state to them.

import type { LibraryGame } from '../api/contract'

export type SortKey = 'name' | 'recent' | 'completion' | 'hltb'

export const SORTS: { key: SortKey; label: string }[] = [
  { key: 'name', label: 'Name' },
  { key: 'recent', label: 'Recently played' },
  { key: 'completion', label: 'Completion' },
  { key: 'hltb', label: 'Shortest (HLTB)' },
]

export interface Filters {
  hideCompleted: boolean
  installedOnly: boolean
  pickableOnly: boolean
}

export const NO_FILTERS: Filters = { hideCompleted: false, installedOnly: false, pickableOnly: false }

/** Achievement percentage, or null when there is no achievement data. */
export function completion(g: LibraryGame): number | null {
  return g.achievements_total > 0 ? (100 * g.achievements_unlocked) / g.achievements_total : null
}

export const isCompleted = (g: LibraryGame) =>
  g.achievements_total > 0 && g.achievements_unlocked >= g.achievements_total

/** Missing values sort last whichever way the key runs. */
function byNullable(a: number | null, b: number | null, desc: boolean): number {
  if (a === null || b === null) return (a === null ? 1 : 0) - (b === null ? 1 : 0)
  return desc ? b - a : a - b
}

const COMPARE: Record<SortKey, (a: LibraryGame, b: LibraryGame) => number> = {
  name: () => 0,
  recent: (a, b) => byNullable(a.last_played, b.last_played, true),
  completion: (a, b) => byNullable(completion(a), completion(b), true),
  hltb: (a, b) => byNullable(a.hltb_hours, b.hltb_hours, false),
}

export function sortGames(games: readonly LibraryGame[], key: SortKey): LibraryGame[] {
  return [...games].sort((a, b) => COMPARE[key](a, b) || a.name.localeCompare(b.name))
}

export function filterGames(
  games: readonly LibraryGame[],
  f: Filters,
  pickable: (g: LibraryGame) => boolean,
): LibraryGame[] {
  return games.filter(
    (g) =>
      !(f.hideCompleted && isCompleted(g)) &&
      !(f.installedOnly && !g.installed) &&
      !(f.pickableOnly && !pickable(g)),
  )
}

/** "45% · 12 h HLTB · 3.2 h played", the card's one meta line. */
export function metaLine(g: LibraryGame): string {
  const pct = completion(g)
  const parts = [pct === null ? 'No achievements' : `${Math.floor(pct)}%`]
  if (g.hltb_hours !== null) parts.push(`${hours(g.hltb_hours)} HLTB`)
  if (g.playtime_minutes > 0) parts.push(`${hours(g.playtime_minutes / 60)} played`)
  return parts.join(' · ')
}

function hours(h: number): string {
  return h >= 10 ? `${Math.round(h)} h` : `${h.toFixed(1)} h`
}
