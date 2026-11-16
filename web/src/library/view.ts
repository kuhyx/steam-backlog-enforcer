// Sorting, filtering and labels for the library browser. Pure functions, so
// the grid component only wires state to them.

import type { LibraryGame } from '../api/contract'
import type { IconId } from '../icons/registry'
import { iconInline } from '../icons/render'
import { h, type Child } from '../lib/dom'

export type SortKey = 'name' | 'recent' | 'completion' | 'hltb'

/** `label` is spoken only; the sort select paints `icon`. */
export const SORTS: { key: SortKey; label: string; icon: IconId }[] = [
  { key: 'name', label: 'Name', icon: 'lib.name' },
  { key: 'recent', label: 'Recently played', icon: 'lib.recent' },
  { key: 'completion', label: 'Completion', icon: 'lib.completion' },
  { key: 'hltb', label: 'Shortest (HLTB)', icon: 'lib.hltb' },
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

/** "45% · 12 h HLTB · 3.2 h played", the card's meta line (spoken only). */
export function metaLine(g: LibraryGame): string {
  const pct = completion(g)
  const parts = [pct === null ? 'No achievements' : `${Math.floor(pct)}%`]
  if (g.hltb_hours !== null) parts.push(`${hours(g.hltb_hours)} HLTB`)
  if (g.playtime_minutes > 0) parts.push(`${hours(g.playtime_minutes / 60)} played`)
  return parts.join(' · ')
}

/** The painted meta line: "🏆 45% · ⏱️ 12 h · ▶️ 3.2 h" (🏆 — without achievements), icons by id. */
export function metaGlyphs(g: LibraryGame): Child[] {
  const pct = completion(g)
  const parts: Child[][] = [[iconInline('lib.completion'), ` ${pct === null ? '—' : `${Math.floor(pct)}%`}`]]
  if (g.hltb_hours !== null) parts.push([iconInline('lib.hltb'), ` ${hours(g.hltb_hours)}`])
  if (g.playtime_minutes > 0) parts.push([iconInline('lib.played'), ` ${hours(g.playtime_minutes / 60)}`])
  return parts.flatMap((part, i) => (i === 0 ? part : [' · ', ...part]))
}

function hours(h: number): string {
  return h >= 10 ? `${Math.round(h)} h` : `${h.toFixed(1)} h`
}

/** Icon for a server ineligibility reason; a date in a skip or block stays painted. */
export function reasonGlyph(reason: string): Child[] {
  const date = /\d{4}-\d{2}-\d{2}/.exec(reason)?.[0]
  if (reason.includes('100%')) return [iconInline('lib.why.complete')]
  if (/no achievements/i.test(reason)) return [iconInline('lib.why.noach')]
  const id = /skip/i.test(reason) ? 'lib.why.skipped' : 'lib.why.blocked'
  return date ? [iconInline(id), ` ${date}`] : [iconInline(id)]
}

/** Glyphs painted, words spoken: `text` shown as `painted` with an sr-only twin. */
export function spokenGlyphs(painted: Child, text: string, className: string): HTMLSpanElement {
  return h('span', { class: className }, h('span', { 'aria-hidden': 'true' }, painted), h('span', { class: 'sr-only' }, text))
}

/** A suggestion's second line: the reason it cannot be picked, else the meta line. */
export function reasonOrMeta(reason: string | null, g: LibraryGame, className: string): HTMLSpanElement {
  return reason === null ? spokenGlyphs(metaGlyphs(g), metaLine(g), className) : spokenGlyphs(reasonGlyph(reason), reason, className)
}
