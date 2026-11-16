// Icon words: the TS mirror of DOCS-web-control-api.md, "Icon words".
// Split out of contract.ts like jobContract.ts; contract.ts re-exports it.

/** One icon's picks. No `word` key: not answered; `word: null`: skipped; `glyph: null`: default. */
export interface IconChoice {
  word?: string | null
  glyph?: string | null
}

/** `web/src/ui/icon_words.json`; an absent id is unanswered. */
export interface IconLedger {
  version: 1
  icons: Record<string, IconChoice>
}

/**
 * `POST|PUT /api/icon-words/{id}` body: `word` (text, or null to skip) and/or
 * `glyph` (one of the icon's 3 alternatives, or null / the default to reset).
 * Answers the whole `IconLedger`.
 */
export type IconChoiceUpdate = { word: string | null } | { glyph: string | null } | { word: string | null; glyph: string | null }

/** Every served page carries the ledger in `<script type="application/json" id=…>`. */
export const ICON_WORDS_SCRIPT = 'sbe-icon-words'

/** A manual word: 1–40 characters after whitespace collapses, no control characters. */
export const ICON_WORD_MAX = 40

export const ICON_WORDS_ENDPOINTS = {
  ledger: '/api/icon-words',
  icon: (id: string) => `/api/icon-words/${id}`,
} as const
