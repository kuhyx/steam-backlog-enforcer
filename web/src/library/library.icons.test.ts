// Pass-2 icon wiring for the library browser: sort options and placeholders
// show the glyph plus the user's word as text, badges and counts draw the
// word right of the icon, spoken labels stay.

import { describe, expect, it, vi } from 'vitest'
import { makeLibGame } from '../test/fixtures'
import { useIcons } from '../test/iconLedger'
import { painted } from '../test/painted'
import { BrowserToolbar } from './browserToolbar'
import { gameCard } from './gameCard'

function toolbar(): BrowserToolbar {
  const bar = new BrowserToolbar({ onInput: vi.fn(), onChoose: vi.fn(), reason: () => null, onSort: vi.fn(), onFilter: vi.fn() })
  document.body.append(bar.el)
  return bar
}

describe('library toolbar by id', () => {
  it('writes the glyph and word into the search placeholder and the sort options', () => {
    useIcons({ 'lib.search': { word: 'find', glyph: '🔎' }, 'lib.hltb': { word: 'length' } })
    const bar = toolbar()
    expect(bar.el.querySelector('input[type=search]')).toHaveAttribute('placeholder', '🔎 Find')
    const options = [...bar.el.querySelectorAll('option')]
    expect(options.map((o) => o.textContent)).toEqual(['🔤', '🕐', '🏆', '⏱️ Length'])
    expect(options[3]).toHaveAttribute('aria-label', 'Shortest (HLTB)')
  })

  it('draws the sort label, the filters and the count with words, aria unchanged', () => {
    useIcons({
      'lib.sort': { word: 'order' },
      'dash.installed': { word: 'local' },
      'lib.count': { word: 'games' },
      'lib.relevance': { glyph: '📊' },
    })
    const bar = toolbar()
    bar.setCount(3, 5, true)
    expect(painted(bar.el.querySelector('.lib-sort'))).toContain('↕️Order')
    expect(painted(bar.el.querySelector('.lib-filters label:nth-of-type(2)'))).toBe('💾Local')
    expect(bar.el.querySelector('.lib-count [aria-hidden]')?.textContent).toBe('🎮Games 3/5 📊')
    expect(bar.el.querySelector('.lib-count .sr-only')?.textContent).toBe('3 of 5 games · by relevance')
    expect(bar.el.querySelector('.lib-filters .sr-only')?.textContent).toBe('Filters')
  })
})

describe('game card badges by id', () => {
  it('draws the assigned and installed badges with their words, spoken names unchanged', () => {
    useIcons({ 'assigned.game': { word: 'target' }, 'dash.installed': { glyph: '📥' } })
    const card = gameCard(makeLibGame({ assigned: true, installed: true }))
    const [assigned, installed] = [...card.querySelectorAll('.game-badges .pill')]
    expect(painted(assigned)).toBe('🎯Target')
    expect(assigned.querySelector('.sr-only')?.textContent).toBe('assigned')
    expect(painted(installed)).toBe('📥')
    expect(installed.querySelector('.sr-only')?.textContent).toBe('installed')
  })
})
