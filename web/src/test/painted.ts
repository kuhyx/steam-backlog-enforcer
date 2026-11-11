// Test helper: the text an element paints, i.e. its textContent without the
// spoken-only (.sr-only) words, whitespace collapsed.

export function painted(el: Element | null | undefined): string {
  if (!el) return ''
  const copy = el.cloneNode(true) as Element
  for (const s of copy.querySelectorAll('.sr-only')) s.remove()
  return copy.textContent.replace(/\s+/g, ' ').trim()
}
