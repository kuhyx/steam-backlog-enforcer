// The one casing rule for every icon word, after cleanup-plate's TextCase:
// sentence case. The first letter of the text is upper-case, every later word
// starts lower-case, except the acronyms / proper nouns in KEEP, which always
// get their listed spelling. Only first letters change: typos, punctuation and
// the rest of a word stay verbatim. Applied at render time; the user's ledger
// is never rewritten. Add a new acronym or name HERE, nowhere else.

export const KEEP: readonly string[] = ['API', 'CDP', 'DLC', 'HLTB', 'ID', 'OK', 'Steam', 'UI']

const EDGE = /^[,.;:!?()"']*/
const TAIL = /[,.;:!?()"']*$/

function caseWord(word: string, first: boolean): string {
  const lead = word.slice(0, word.length - word.replace(EDGE, '').length)
  const core = word.slice(lead.length).replace(TAIL, '')
  if (core === '') return word
  const keep = KEEP.find((k) => k.toLowerCase() === core.toLowerCase())
  if (keep) return lead + keep + word.slice(lead.length + core.length)
  const letter = word.charAt(lead.length)
  const cased = first ? letter.toUpperCase() : letter.toLowerCase()
  return lead + cased + word.slice(lead.length + 1)
}

export function sentenceCase(text: string): string {
  return text
    .split(' ')
    .map((w, i) => caseWord(w, i === 0))
    .join(' ')
}
