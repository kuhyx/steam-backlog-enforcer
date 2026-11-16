import { describe, expect, it } from 'vitest'
import { normalizeWord, wordProblem } from './wordRules'

describe('manual words (mirror of the server rules)', () => {
  it('collapses whitespace and keeps casing', () => {
    expect(normalizeWord('  My   OWN\tword\n ')).toBe('My OWN word')
  })

  it.each(['My own words', 'x', 'HLTB 100%', 'I got an achievement!', '🏆'.repeat(40), 'a'.repeat(40)])(
    'accepts %j',
    (text) => {
      expect(wordProblem(text)).toBe('')
    },
  )

  it.each([
    ['', 'empty'],
    ['   ', 'empty'],
    ['a'.repeat(41), 'too_long'],
    ['bad\u0000word', 'control'],
    ['esc\u001b', 'control'],
    ['del\u007f', 'control'],
  ])('refuses %j as %s', (text, why) => {
    expect(wordProblem(text)).toBe(why)
  })
})
