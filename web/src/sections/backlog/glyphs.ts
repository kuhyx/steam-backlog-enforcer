// Backlog pictograms by registry id (textgate: these are painted, the words
// are spoken only). One icon per idea across the stats card, the planner
// filters, the summary cards and the table headers, so an icon learned in one
// place reads the same everywhere, and the user's word follows it.

import type { IconId } from '../../icons/registry'
import { iconText } from '../../icons/iconText'
import { iconInline } from '../../icons/render'
import type { EstimateBasis } from '../../types'
import { glyph } from '../../ui/build'

export const BASIS_ICON = {
  rush: 'basis.rush',
  leisure: 'basis.leisure',
  worst: 'basis.worst',
  pace: 'basis.pace',
} as const satisfies Record<EstimateBasis, IconId>

/** Player style vs HLTB; the `--<style>` class adds the colour channel. */
const STYLE_ICON: Record<string, IconId> = {
  faster_than_rush: 'style.fast',
  rush_to_leisure: 'style.between',
  slower_than_leisure: 'style.slow',
  unknown: 'state.unknown',
}

const STYLE_SPOKEN: Record<string, string> = {
  faster_than_rush: 'Faster than HLTB rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than HLTB leisure',
  unknown: 'Not enough finished games yet',
}

/** A player style: its icon painted (the class adds colour), its sentence spoken. */
export const styleGlyph = (style: string) =>
  glyph(STYLE_ICON[style] ?? 'state.unknown', STYLE_SPOKEN[style] ?? style, `player-insight-style player-insight-style--${style}`)

/** ProtonDB tiers, best to worst: medals, then a crash and an hourglass. */
const TIER_ICON: Record<string, IconId> = {
  native: 'tier.native',
  platinum: 'tier.platinum',
  gold: 'tier.gold',
  silver: 'tier.silver',
  bronze: 'tier.bronze',
  borked: 'tier.borked',
  pending: 'tier.pending',
}

/** A tierLabel() string (`gold`, `gold / silver`, `—`) as icons; an unknown tier is the unknown mark. */
export function tierMarks(label: string): (HTMLSpanElement | string)[] {
  if (!label || label === '—') return ['—']
  return label
    .split(' / ')
    .flatMap((tier, i) => [...(i ? ['/'] : []), iconInline(TIER_ICON[tier] ?? 'state.unknown')])
}

/** `tierMarks` as plain text (glyph, then word) for an `<option>`, which cannot hold markup. */
export function tierText(label: string): string {
  if (!label || label === '—') return '—'
  return label
    .split(' / ')
    .map((tier) => iconText(TIER_ICON[tier] ?? 'state.unknown'))
    .join('/')
}

const KEEP_ICON: Record<string, IconId> = { kept: 'keep.kept', excluded: 'keep.excluded' }

/** The keep filter's value as plain option text. */
export const keepText = (value: string) => iconText(KEEP_ICON[value])
