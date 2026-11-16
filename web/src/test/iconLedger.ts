// Test helpers for the icon-word ledger: set it directly, or plant the
// `<script id="sbe-icon-words">` the Python server injects into every page.

import { ICON_WORDS_SCRIPT, type IconChoice } from '../api/iconWordsContract'
import { resetLedger, setLedger } from '../icons/ledger'

/** Use `icons` as the loaded ledger (what a page load would have read). */
export function useIcons(icons: Record<string, IconChoice>): void {
  setLedger({ version: 1, icons })
}

/** Plant the server's injected payload, then forget the cached ledger. */
export function injectLedgerScript(payload: unknown): void {
  document.getElementById(ICON_WORDS_SCRIPT)?.remove()
  const script = document.createElement('script')
  script.type = 'application/json'
  script.id = ICON_WORDS_SCRIPT
  script.textContent = typeof payload === 'string' ? payload : JSON.stringify(payload)
  document.head.append(script)
  resetLedger()
}
