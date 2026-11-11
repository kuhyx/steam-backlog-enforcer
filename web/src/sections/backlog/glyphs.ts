// Backlog pictograms (textgate: these are painted, the words are spoken only).
// One glyph per idea across the stats card, the planner filters, the summary
// cards and the table headers, so a glyph learned in one place reads the same
// everywhere.

import type { EstimateBasis } from '../../types'
import { glyph } from '../../ui/build'

export const BASIS_GLYPH: Record<EstimateBasis, string> = {
  rush: '🐇',
  leisure: '🐢',
  worst: '🐌',
  pace: '👤',
}

/** Player style vs HLTB; the `--<style>` class adds the colour channel. */
export const STYLE_GLYPH: Record<string, string> = {
  faster_than_rush: '⚡',
  rush_to_leisure: '🐇↔🐢',
  slower_than_leisure: '🐌',
  unknown: '❔',
}

export const STYLE_SPOKEN: Record<string, string> = {
  faster_than_rush: 'Faster than HLTB rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than HLTB leisure',
  unknown: 'Not enough finished games yet',
}

/** A player style: its glyph painted (the class adds colour), its sentence spoken. */
export const styleGlyph = (style: string) =>
  glyph(STYLE_GLYPH[style] ?? '❔', STYLE_SPOKEN[style] ?? style, `player-insight-style player-insight-style--${style}`)

/** ProtonDB tiers, best to worst: medals, then a crash and an hourglass. */
export const TIER_GLYPH: Record<string, string> = {
  native: '⭐',
  platinum: '💎',
  gold: '🥇',
  silver: '🥈',
  bronze: '🥉',
  borked: '💥',
  pending: '⏳',
}

const tierGlyph = (tier: string) => TIER_GLYPH[tier] ?? '❔'

/** A tierLabel() string (`gold`, `gold / silver`, `—`) as glyphs. */
export function tierGlyphs(label: string): string {
  if (!label || label === '—') return '—'
  return label.split(' / ').map(tierGlyph).join('/')
}

export const KEEP_GLYPH: Record<string, string> = { kept: '📌', excluded: '🚫' }

/** "Any value" in a filter select or segmented control. */
export const ANY_GLYPH = '✱'
