// iconInline: the painted-only icon (no spoken text) used inside said(...),
// buttons and labels, plus the shared builders that now take ids.

import { describe, expect, it } from 'vitest'
import { useIcons } from '../test/iconLedger'
import { copyButton, empty, pill } from '../ui/build'
import { setWordsHidden } from './ledger'
import { iconInline } from './render'

describe('iconInline', () => {
  it('is the glyph mark alone when there is no word', () => {
    const el = iconInline('state.wait', 'x')
    expect(el.textContent).toBe('⏳')
    expect(el).toHaveAttribute('aria-hidden', 'true')
    expect(el).toHaveAttribute('data-icon', 'state.wait')
    expect(el).toHaveClass('x')
  })

  it('paints the chosen alternative glyph', () => {
    useIcons({ 'state.wait': { word: null, glyph: '⌛' } })
    expect(iconInline('state.wait').textContent).toBe('⌛')
  })

  it('puts the word right of the icon in one row, both aria-hidden', () => {
    useIcons({ 'state.wait': { word: 'busy' } })
    const el = iconInline('state.wait')
    expect(el).toHaveClass('icon-inline', 'has-word')
    const [icon, word] = [...el.children]
    expect(icon.textContent).toBe('⏳')
    expect(word).toHaveClass('icon-word')
    expect(word).toHaveAttribute('aria-hidden', 'true')
    expect(word.textContent).toBe('Busy')
  })

  it('draws no word while words are hidden', () => {
    useIcons({ 'state.wait': { word: 'busy' } })
    setWordsHidden(true)
    expect(iconInline('state.wait').querySelector('.icon-word')).toBeNull()
    setWordsHidden(false)
  })
})

describe('builders that take ids', () => {
  it('empty paints the empty icon and its word, the sentence stays spoken', () => {
    useIcons({ 'state.empty': { word: 'nothing' } })
    const el = empty('No games')
    expect(el.querySelector('.empty-icon')?.textContent).toBe('📭')
    expect(el.querySelector('.icon-word')?.textContent).toBe('Nothing')
    expect(el.querySelector('.sr-only')?.textContent).toBe('No games')
  })

  it('pill paints its icon, word and spoken text', () => {
    useIcons({ 'state.warn': { word: 'attention', glyph: '🟠' } })
    const el = pill('warning', 'locked', 'state.warn')
    expect(el.className).toBe('pill pill-warning')
    expect(el.querySelector('.pill-icon')?.textContent).toBe('🟠')
    expect(el.querySelector('.icon-word')?.textContent).toBe('Attention')
    expect(el.querySelector('.sr-only')?.textContent).toBe('locked')
  })

  it('copyButton paints its icon and word, then the done icon after a copy', async () => {
    useIcons({ 'copy.command': { word: 'copy' }, 'copy.done': { word: 'copied', glyph: '🎉' } })
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.resolve() }, configurable: true })
    const btn = copyButton('sudo x')
    expect(btn.textContent).toBe('📋Copy')
    btn.click()
    await Promise.resolve()
    await Promise.resolve()
    expect(btn.textContent).toBe('🎉Copied')
    expect(btn).toHaveAttribute('aria-label', 'Copied')
  })
})
