// Textgate check over the built site: list every chrome word a page paints
// before its custom elements hydrate (layout, page heads). Spoken-only text (.sr-only, aria-hidden, the focus-only skip link)
// is ignored. Exit 1 when any page paints a word, so it works as a gate.
//
// Usage: node scripts/visible_words.mjs [distDir]   (run `pnpm build` first)

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { JSDOM } from 'jsdom'

const WORD_RE = /[A-Za-z]{2,}/
const SPOKEN = '.sr-only, [aria-hidden="true"], .skip, script, style, template'

/** @param {string} dir @returns {string[]} */
function htmlFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return htmlFiles(p)
    return name.endsWith('.html') ? [p] : []
  })
}

/** @param {string} html @returns {string[]} */
export function visibleWords(html) {
  const { document } = new JSDOM(html).window
  for (const el of document.querySelectorAll(SPOKEN)) el.remove()
  const out = []
  const walker = document.createTreeWalker(document.body, 4 /* SHOW_TEXT */)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.textContent?.trim() ?? ''
    if (WORD_RE.test(t)) out.push(t)
  }
  // command-button's `label` is spoken only (aria-label) once it hydrates;
  // src/test/textgate.commands.guard.test.ts pins that.
  return out
}

const dist = process.argv[2] ?? 'dist'
let total = 0
for (const file of htmlFiles(dist).sort()) {
  const words = visibleWords(readFileSync(file, 'utf8'))
  total += words.length
  if (words.length) console.log(`${relative(dist, file)} (${words.length}): ${words.join(' | ')}`)
}
console.log(`total: ${total}`)
process.exit(total ? 1 : 0)
