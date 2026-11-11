// Textgate guard helper (textgate-rework R6): the words an element paints.
// Spoken-only text (.sr-only, [hidden]) and content the caller passes in
// `allowed` (game names, server messages) do not count. aria-hidden text
// still paints, so it counts.

const WORD_RE = /[A-Za-z]{2,}/

function spokenOnly(el: Element | null): boolean {
  for (let cur = el; cur; cur = cur.parentElement) {
    if (cur.classList.contains('sr-only')) return true
    if (cur instanceof HTMLElement && cur.hidden) return true
  }
  return false
}

/** Visible text nodes holding a word of 2+ letters, minus `allowed` content. */
export function visibleWords(root: Element, allowed: readonly string[] = []): string[] {
  const out: string[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent?.trim() ?? ''
    if (!WORD_RE.test(t) || spokenOnly(n.parentElement) || allowed.includes(t)) continue
    out.push(t)
  }
  return out
}
