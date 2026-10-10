// Typo-tolerant game-name search for the library browser.
//
// Names and queries go through the same normalisation (case, accents,
// punctuation, "witcher3" → "witcher 3", roman numerals → arabic), then each
// query word must match some name word exactly, as a prefix, as a substring,
// or within a small edit distance ("wicher" → "witcher"). A lone "i" is never
// read as 1: it is a word ("I Am Bread") far more often than a numeral.

const ROMAN: Record<string, string> = {
  ii: '2', iii: '3', iv: '4', v: '5', vi: '6', vii: '7', viii: '8', ix: '9', x: '10',
  xi: '11', xii: '12', xiii: '13', xiv: '14', xv: '15', xvi: '16', xx: '20',
}

/** Lower-case words without accents or punctuation, digit runs split off. */
function words(text: string): string[] {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/['’]/g, '')
    .replace(/([a-z])(\d)|(\d)([a-z])/g, '$1$3 $2$4')
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
}

export interface Searchable {
  tokens: string[]
  /** Words before numeral conversion, joined: "xcom" still finds "X-COM". */
  compact: string
  text: string
}

export function normalise(text: string): Searchable {
  const raw = words(text)
  const tokens = raw.map((w) => ROMAN[w] ?? w)
  return { tokens, compact: raw.join(''), text: tokens.join(' ') }
}

/** Optimal-string-alignment distance, giving up once it exceeds `max`. */
export function editDistance(a: string, b: string, max: number): number {
  if (Math.abs(a.length - b.length) > max) return max + 1
  let prev2: number[] = []
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    const cur = [i]
    let rowMin = i
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, prev2[j - 2] + 1)
      }
      cur.push(v)
      rowMin = Math.min(rowMin, v)
    }
    if (rowMin > max) return max + 1
    prev2 = prev
    prev = cur
  }
  return prev[b.length]
}

const allowedTypos = (word: string) => (word.length < 4 ? 0 : word.length < 7 ? 1 : 2)

/** How well one query word matches one name word, 0 when it does not. */
function wordScore(q: string, n: string): number {
  if (n === q) return 1
  if (n.startsWith(q)) return 0.85
  if (q.length >= 3 && n.includes(q)) return 0.6
  const max = /^\d+$/.test(q) ? 0 : allowedTypos(q)
  if (max === 0) return 0
  // Whole word, or the start of a longer one the user is still typing.
  const d = Math.min(editDistance(q, n, max), editDistance(q, n.slice(0, q.length), max))
  return d <= max ? 0.7 - 0.15 * d : 0
}

/** Relevance of `name` for `query` (higher is better), or 0 for no match. */
export function score(query: Searchable, name: Searchable): number {
  if (query.tokens.length === 0) return 0
  if (name.text.startsWith(query.text)) return 100 - name.tokens.length
  let total = 0
  let missed = 0
  let longestHit = 0
  let longestMiss = 0
  for (const q of query.tokens) {
    let best = 0
    for (const n of name.tokens) best = Math.max(best, wordScore(q, n))
    if (best === 0) {
      missed++
      longestMiss = Math.max(longestMiss, q.length)
    } else if (!/^\d+$/.test(q)) {
      longestHit = Math.max(longestHit, q.length)
    }
    total += best
  }
  const words = query.tokens.length
  if (missed === 0) return (80 * total) / words - name.tokens.length * 0.5
  if (query.compact.length >= 3 && name.compact.includes(query.compact)) return 40
  // "hollow nite": the main word found, a shorter one beyond repair. Shown,
  // ranked low; a lone "3" or "of" matching is not enough.
  const partial = words >= 2 && missed * 2 <= words && longestHit >= 4 && longestHit >= longestMiss
  return partial ? (30 * total) / words : 0
}

/**
 * Items matching `query`, best first (ties by name). An all-digit query also
 * matches an app id exactly, ranked above everything.
 */
export function search<T extends { app_id: number; name: string }>(
  items: readonly T[],
  index: ReadonlyMap<number, Searchable>,
  query: string,
): T[] {
  const q = normalise(query)
  const id = /^\d+$/.test(query.trim()) ? Number(query.trim()) : null
  const hits: [T, number][] = []
  for (const item of items) {
    const s = item.app_id === id ? 1000 : score(q, index.get(item.app_id) ?? normalise(item.name))
    if (s > 0) hits.push([item, s])
  }
  hits.sort((a, b) => b[1] - a[1] || a[0].name.localeCompare(b[0].name))
  return hits.map(([item]) => item)
}

/** Normalised names by app id, built once per library load. */
export function buildIndex(items: readonly { app_id: number; name: string }[]): Map<number, Searchable> {
  return new Map(items.map((i) => [i.app_id, normalise(i.name)]))
}
