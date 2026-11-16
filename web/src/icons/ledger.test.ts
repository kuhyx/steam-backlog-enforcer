import { describe, expect, it, vi } from 'vitest'
import { injectLedgerScript, useIcons } from '../test/iconLedger'
import { choiceOf, isAnswered, ledger, ledgerError, setWordsHidden, wordsHidden, WORDS_HIDDEN_KEY } from './ledger'

describe('ledger', () => {
  it('is empty when the page carries none (dev server, tests)', () => {
    expect(ledger()).toEqual({ version: 1, icons: {} })
    expect(isAnswered('cmd.done')).toBe(false)
    expect(ledgerError()).toBeNull()
  })

  it('reads the payload the server injected into the page, once', () => {
    injectLedgerScript({ version: 1, icons: { 'cmd.done': { word: 'Won', glyph: '🎉' } } })
    expect(choiceOf('cmd.done')).toEqual({ word: 'Won', glyph: '🎉' })
    document.getElementById('sbe-icon-words')?.remove()
    expect(choiceOf('cmd.done').word).toBe('Won')
  })

  it('counts an id as answered only once its word is decided (text or skip)', () => {
    useIcons({ 'cmd.done': { word: null, glyph: null }, 'cmd.scan': { glyph: '📡' }, 'cmd.pick': { word: 'roll' } })
    expect(isAnswered('cmd.done')).toBe(true)
    expect(isAnswered('cmd.pick')).toBe(true)
    expect(isAnswered('cmd.scan')).toBe(false)
    expect(isAnswered('cmd.check')).toBe(false)
    expect(choiceOf('cmd.check')).toEqual({})
  })

  it('fails loudly on a corrupt ledger the server reported', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    injectLedgerScript({ error: 'op_failed', message: 'kept aside as x.corrupt' })
    expect(ledger().icons).toEqual({})
    expect(ledgerError()).toBe('kept aside as x.corrupt')
    expect(err).toHaveBeenCalledWith(expect.stringContaining('x.corrupt'))
  })

  it('names the failure even when the error body has no message', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    injectLedgerScript({ error: 'op_failed' })
    expect(ledgerError()).toBe('The icon-word ledger is unreadable.')
  })

  it('fails loudly on a payload that does not parse', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    injectLedgerScript('{nope')
    expect(ledger().icons).toEqual({})
    expect(ledgerError()).toMatch(/does not parse/)
    expect(err).toHaveBeenCalled()
  })
})

describe('words-hidden setting', () => {
  it('defaults to words shown and persists in localStorage', () => {
    expect(wordsHidden()).toBe(false)
    setWordsHidden(true)
    expect(wordsHidden()).toBe(true)
    expect(localStorage.getItem(WORDS_HIDDEN_KEY)).toBe('1')
    setWordsHidden(false)
    expect(wordsHidden()).toBe(false)
    expect(localStorage.getItem(WORDS_HIDDEN_KEY)).toBeNull()
  })
})
