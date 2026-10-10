import { describe, expect, it } from 'vitest'
import { buildIndex, editDistance, normalise, score, search } from './fuzzy'

const GAMES = [
  { app_id: 1, name: 'The Witcher: Enhanced Edition' },
  { app_id: 2, name: 'The Witcher 2: Assassins of Kings' },
  { app_id: 3, name: 'The Witcher 3: Wild Hunt' },
  { app_id: 4, name: 'Age of Empires III' },
  { app_id: 5, name: 'Hollow Knight' },
  { app_id: 6, name: 'X-COM: Enemy Unknown' },
  { app_id: 7, name: 'I Am Bread' },
  { app_id: 8, name: "Baldur's Gate & Friends" },
  { app_id: 9, name: 'Pokémon Stadium 2' },
]
const INDEX = buildIndex(GAMES)
const find = (q: string) => search(GAMES, INDEX, q).map((g) => g.name)

describe('normalise', () => {
  it('strips case, accents and punctuation', () => {
    expect(normalise('Pokémon  Stadium!').text).toBe('pokemon stadium')
    expect(normalise("Baldur's Gate & Co").tokens).toEqual(['baldurs', 'gate', 'and', 'co'])
  })

  it('splits letter/digit runs', () => {
    expect(normalise('witcher3').tokens).toEqual(['witcher', '3'])
    expect(normalise('3d').tokens).toEqual(['3', 'd'])
  })

  it('converts roman numerals but never a lone i', () => {
    expect(normalise('Witcher III').tokens).toEqual(['witcher', '3'])
    expect(normalise('I Am Bread').tokens).toEqual(['i', 'am', 'bread'])
  })

  it('keeps the unconverted compact form', () => {
    expect(normalise('X-COM').compact).toBe('xcom')
  })
})

describe('editDistance', () => {
  it('is 0 for equal words and counts edits', () => {
    expect(editDistance('abc', 'abc', 2)).toBe(0)
    expect(editDistance('wicher', 'witcher', 2)).toBe(1)
    expect(editDistance('abcd', 'abdc', 2)).toBe(1) // transposition
  })

  it('gives up past max', () => {
    expect(editDistance('a', 'abcdef', 2)).toBe(3) // length gap
    expect(editDistance('aaaa', 'bbbb', 1)).toBe(2) // row minimum
  })
})

describe('search', () => {
  it('finds Witcher titles for a typo', () => {
    const hits = find('wicher')
    expect(hits).toContain('The Witcher 3: Wild Hunt')
    expect(hits).toContain('The Witcher 2: Assassins of Kings')
    expect(hits).toContain('The Witcher: Enhanced Edition')
  })

  it('matches roman and arabic numerals both ways', () => {
    expect(find('witcher iii')[0]).toBe('The Witcher 3: Wild Hunt')
    expect(find('empires 3')).toContain('Age of Empires III')
    expect(find('age of empires iii')[0]).toBe('Age of Empires III')
  })

  it('does not return Age of Empires III for "witcher 3"', () => {
    const hits = find('witcher 3')
    expect(hits[0]).toBe('The Witcher 3: Wild Hunt')
    expect(hits).not.toContain('Age of Empires III')
  })

  it('finds "xcom" in "X-COM" through the compact form', () => {
    expect(find('xcom')).toEqual(['X-COM: Enemy Unknown'])
  })

  it('joins split words when no single word is close enough', () => {
    const items = [{ app_id: 60, name: 'Spider-Man Remastered' }]
    expect(search(items, buildIndex(items), 'spiderman')).toEqual(items)
  })

  it('does not treat a lone "i" as a numeral', () => {
    expect(find('i')).toEqual(['I Am Bread'])
    expect(find('i am')).toEqual(['I Am Bread'])
  })

  it('matches an app id exactly, ranked first', () => {
    expect(find('5')[0]).toBe('Hollow Knight')
    expect(find(' 3 ')[0]).toBe('The Witcher 3: Wild Hunt')
  })

  it('shows a partial match with one word beyond repair', () => {
    expect(find('hollow nite')).toEqual(['Hollow Knight'])
  })

  it('rejects a lone number or short word as a partial match', () => {
    expect(find('witcher 99')).not.toContain('Age of Empires III')
    expect(find('qqqq zz')).toEqual([])
  })

  it('matches substrings of three or more letters', () => {
    expect(find('aldu')).toEqual(["Baldur's Gate & Friends"])
    expect(find('nd')).toEqual([])
    expect(find('wit')).toHaveLength(3) // prefix of a later word
    expect(find('zz')).toEqual([])
  })

  it('returns nothing for an empty or punctuation-only query', () => {
    expect(find('')).toEqual([])
    expect(find('---')).toEqual([])
  })

  it('breaks score ties by name', () => {
    const items = [
      { app_id: 20, name: 'Zed Game' },
      { app_id: 21, name: 'Alpha Game' },
    ]
    const hits = search(items, buildIndex(items), 'game').map((g) => g.name)
    expect(hits).toEqual(['Alpha Game', 'Zed Game'])
  })

  it('normalises on the fly for an item missing from the index', () => {
    const extra = [{ app_id: 50, name: 'Hollow Knight' }]
    expect(search(extra, new Map(), 'hollow')).toEqual(extra)
  })
})

describe('score', () => {
  it('ranks a prefix match above a fuzzy one', () => {
    const q = normalise('hollow')
    expect(score(q, normalise('Hollow Knight'))).toBeGreaterThan(score(q, normalise('Hallow Night')))
  })

  it('requires an exact match for numbers', () => {
    expect(score(normalise('2'), normalise('Game 3'))).toBe(0)
  })

  it('is 0 without query words', () => {
    expect(score(normalise(''), normalise('Anything'))).toBe(0)
  })
})
