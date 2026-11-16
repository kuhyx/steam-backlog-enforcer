// Manual icon words, the client's copy of the server's rule
// (_web_icon_words.normalize_word): any words, casing kept, whitespace runs
// collapsed, 1–40 characters, no control characters. The server re-checks;
// this only lets the picker flag a bad entry before sending it.

import { ICON_WORD_MAX } from '../api/iconWordsContract'

// Spelled out (not \s) so it matches the Python side character for character.
const SPACE = /[\t\n\v\f\r \u00a0\u2000-\u200a\u2028\u2029\u202f\u3000]+/g
// eslint-disable-next-line no-control-regex -- control characters are the point
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/

export type WordProblem = '' | 'empty' | 'too_long' | 'control'

export function normalizeWord(text: string): string {
  return text.replace(SPACE, ' ').trim()
}

/** '' when `text` is a storable word, else why not. Length counts code points, like Python. */
export function wordProblem(text: string): WordProblem {
  const word = normalizeWord(text)
  if (word === '') return 'empty'
  if (Array.from(word).length > ICON_WORD_MAX) return 'too_long'
  return CONTROL.test(word) ? 'control' : ''
}
