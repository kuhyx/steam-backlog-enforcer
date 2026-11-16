// The icon-word ledger as this page knows it. The Python server injects it
// into every page (`<script type="application/json" id="sbe-icon-words">`),
// so it is read synchronously on first use and every renderer sees the same
// picks; the /words picker replaces it after each save. A corrupt ledger
// arrives as the server's error body: no words are drawn and the error is
// logged (and shown on /words), never swallowed.

import { ICON_WORDS_SCRIPT, type IconChoice, type IconLedger } from '../api/iconWordsContract'

/** localStorage key of the one "hide all words" setting; absent = words shown. */
export const WORDS_HIDDEN_KEY = 'sbe-icon-words-hidden'

const EMPTY: IconLedger = { version: 1, icons: {} }

let cached: IconLedger | null = null
let failure: string | null = null

function readPage(): IconLedger {
  const raw = document.getElementById(ICON_WORDS_SCRIPT)?.textContent
  if (raw === undefined) return EMPTY
  let parsed: Partial<IconLedger> & { message?: string }
  try {
    parsed = JSON.parse(raw) as typeof parsed
  } catch (e) {
    parsed = { message: `The icon-word ledger in this page does not parse: ${String(e)}` }
  }
  if (parsed.icons) return parsed as IconLedger
  failure = parsed.message ?? 'The icon-word ledger is unreadable.'
  console.error(`[sbe] icon words off: ${failure}`)
  return EMPTY
}

export function ledger(): IconLedger {
  cached ??= readPage()
  return cached
}

/** Use `next` from now on (the picker, after the server answered a save). */
export function setLedger(next: IconLedger): void {
  cached = next
  failure = null
}

/** Forget the cached ledger so the next read re-reads the page (tests). */
export function resetLedger(): void {
  cached = null
  failure = null
}

/** The server's message when the page carried a corrupt ledger, else null. */
export function ledgerError(): string | null {
  ledger()
  return failure
}

export function choiceOf(id: string): IconChoice {
  return ledger().icons[id] ?? {}
}

/** Answered = the word is decided (text or a skip); a glyph alone is not enough. */
export function isAnswered(id: string): boolean {
  return 'word' in choiceOf(id)
}

export function wordsHidden(): boolean {
  return localStorage.getItem(WORDS_HIDDEN_KEY) === '1'
}

export function setWordsHidden(hidden: boolean): void {
  if (hidden) localStorage.setItem(WORDS_HIDDEN_KEY, '1')
  else localStorage.removeItem(WORDS_HIDDEN_KEY)
}
