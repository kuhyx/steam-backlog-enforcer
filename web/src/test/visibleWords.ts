// Textgate guard helper (textgate-rework R6): the words an element paints.
// Spoken-only text (.sr-only, [hidden]) and content the caller passes in
// `allowed` (game names, server messages) do not count. aria-hidden text
// still paints, so it counts. The user's own icon words are the one chrome
// text allowed: an `.icon-word` passes only when it reads exactly what the
// ledger draws for its icon id.

import { iconFor } from '../icons/render'
import { isIconId } from '../icons/registry'

const WORD_RE = /[A-Za-z]{2,}/

function spokenOnly(el: Element | null): boolean {
  for (let cur = el; cur; cur = cur.parentElement) {
    if (cur.classList.contains('sr-only')) return true
    if (cur instanceof HTMLElement && cur.hidden) return true
  }
  return false
}

/** True for the text of an icon word that is the ledger's word for that icon. */
function ledgerWord(el: Element | null, text: string): boolean {
  const id = el?.closest('.icon-word')?.getAttribute('data-icon-word') ?? ''
  return isIconId(id) && iconFor(id).word === text
}

/** Visible text nodes holding a word of 2+ letters, minus `allowed` content. */
export function visibleWords(root: Element, allowed: readonly string[] = []): string[] {
  const out: string[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent?.trim() ?? ''
    if (!WORD_RE.test(t) || spokenOnly(n.parentElement) || allowed.includes(t) || ledgerWord(n.parentElement, t)) continue
    out.push(t)
  }
  return out
}
