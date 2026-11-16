// The icon registry: every icon the UI paints by id, its default glyph, its
// spoken name, what it is and does, 3 one-word suggestions and 3 alternative
// glyphs. The data is registry.json so the Python server can check a glyph
// choice against the same list; this module types it (IconId is the union of
// its keys, so an unregistered id fails the build) and looks it up.
// Order in the file is the picker's order.

import data from './registry.json'

export type IconId = keyof typeof data.icons

export interface IconEntry {
  id: IconId
  glyph: string
  /** The accessible name (aria-label / .sr-only) when a caller gives none. */
  spoken: string
  /** What the icon is and what it does, shown on the /words picker. */
  desc: string
  /** Three distinct one-word suggestions (keys 1/2/3 on the picker). */
  words: readonly string[]
  /** Three glyphs that may replace the default (keys 7/8/9). */
  alts: readonly string[]
}

const RAW: Record<string, Omit<IconEntry, 'id'>> = data.icons

export const ICONS: readonly IconEntry[] = Object.entries(RAW).map(([id, e]) => ({ id: id as IconId, ...e }))

const BY_ID = Object.fromEntries(ICONS.map((e) => [e.id, e])) as Record<IconId, IconEntry>

/** True for a registered id, false for a raw glyph (the old `glyph(icon, spoken)` path). */
export function isIconId(s: string): s is IconId {
  return Object.hasOwn(BY_ID, s)
}

export function iconEntry(id: IconId): IconEntry {
  return BY_ID[id]
}
