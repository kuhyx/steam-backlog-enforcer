// Drawing a registered icon: the glyph (the user's alternative if he chose
// one) and, when he picked a word, that word to the RIGHT of the icon,
// vertically centred (styles/icons.css `.has-word`), in sentence case. The
// word is aria-hidden: the icon's spoken name stays its one accessible name.
// `glyph(id)` in ui/build.ts is the usual entry; these are its parts.

import { h } from '../lib/dom'
import { choiceOf, wordsHidden } from './ledger'
import { iconEntry, isIconId, type IconId } from './registry'
import { sentenceCase } from './textCase'

export interface ResolvedIcon {
  id: IconId
  glyph: string
  /** As drawn (sentence case); '' when skipped, unanswered or hidden. */
  word: string
  spoken: string
}

export function iconFor(id: IconId): ResolvedIcon {
  const entry = iconEntry(id)
  const choice = choiceOf(id)
  const glyph = choice.glyph && entry.alts.includes(choice.glyph) ? choice.glyph : entry.glyph
  const word = typeof choice.word === 'string' && !wordsHidden() ? sentenceCase(choice.word) : ''
  return { id, glyph, word, spoken: entry.spoken }
}

/** The painted glyph alone, tagged with its id (decorateIcons can refresh it). */
export function iconMark(id: IconId, className: string): HTMLSpanElement {
  return h('span', { class: className, 'aria-hidden': 'true', 'data-icon': id }, iconFor(id).glyph)
}

/** The word span that goes right after the icon, or null when it has none. */
export function iconWord(id: IconId): HTMLSpanElement | null {
  const { word } = iconFor(id)
  return word ? h('span', { class: 'icon-word', 'aria-hidden': 'true', 'data-icon-word': id }, word) : null
}

/**
 * Refresh static markup (the Astro sidebar and palette button) from the
 * ledger: each `[data-icon]` gets its current glyph and, right after it, its
 * word. Idempotent, so it can rerun after a pick or a hide toggle.
 */
export function decorateIcons(root: ParentNode): void {
  for (const el of root.querySelectorAll<HTMLElement>('[data-icon]')) {
    const id = String(el.dataset.icon)
    if (!isIconId(id)) continue
    const next = el.nextElementSibling
    if (next?.classList.contains('icon-word')) next.remove()
    el.textContent = iconFor(id).glyph
    const word = iconWord(id)
    if (word) el.after(word)
    el.parentElement?.classList.toggle('has-word', word !== null)
  }
}

/** The static chrome every page shares (sidebar, top bar); run at boot and after a pick. */
export function decorateChrome(doc: Document = document): void {
  for (const el of doc.querySelectorAll('.sidebar, .topbar')) decorateIcons(el)
}
