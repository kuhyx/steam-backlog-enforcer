// An icon as plain text, for the places that cannot hold markup: an input's
// placeholder or an <option>. The glyph (the user's alternative applied),
// then his word right of it when he chose one.

import type { IconId } from './registry'
import { iconFor } from './render'

export function iconText(id: IconId): string {
  const { glyph, word } = iconFor(id)
  return word ? `${glyph} ${word}` : glyph
}
