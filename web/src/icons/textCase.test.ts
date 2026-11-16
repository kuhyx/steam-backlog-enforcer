import { describe, expect, it } from 'vitest'
import { KEEP, sentenceCase } from './textCase'

describe('sentenceCase', () => {
  it.each([
    ['home', 'Home'],
    ['gaming Reset', 'Gaming reset'],
    ['My Own Words', 'My own words'],
    ['buy dlc', 'Buy DLC'],
    ['hltb times', 'HLTB times'],
    ['app Id', 'App ID'],
    ['open steam', 'Open Steam'],
    ['get (dlc)!', 'Get (DLC)!'],
    ['"quoted" word', '"Quoted" word'],
    ['', ''],
    ['42 games', '42 games'],
  ])('%j -> %j', (stored, drawn) => {
    expect(sentenceCase(stored)).toBe(drawn)
  })

  it('changes only first letters: the rest of a word stays verbatim', () => {
    expect(sentenceCase('iPhone sYnc')).toBe('IPhone sYnc')
  })

  it('keeps the acronyms the brief names', () => {
    for (const word of ['DLC', 'HLTB', 'CDP', 'ID']) expect(KEEP).toContain(word)
    expect(sentenceCase('via cdp')).toBe('Via CDP')
  })
})
