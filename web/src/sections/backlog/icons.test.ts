// The backlog page's icons are registry ids: the user's word shows right of
// the icon, a chosen alternative glyph replaces it, spoken names stay.

import { screen } from '@testing-library/dom'
import { afterEach, describe, expect, it } from 'vitest'
import { applyFilters } from '../../estimate'
import { timelineChart } from '../../lib/charts/timeline'
import { makeDataset, makeFilters, makeGame, makePaceVsHltb, makeState } from '../../test/factories'
import { useIcons } from '../../test/iconLedger'
import { GAMES, header, panel, show, table } from '../../test/plannerHelpers'
import { painted } from '../../test/painted'
import { keepText, styleGlyph, tierMarks, tierText } from './glyphs'
import { summaryCards } from './summary'

afterEach(() => {
  history.replaceState(null, '', '/')
})

const wordAfter = (mark: Element | null) => mark?.nextElementSibling?.textContent

describe('backlog icons: filter panel', () => {
  it('draws the basis word right of the icon and keeps the button name', async () => {
    useIcons({ 'basis.rush': { word: 'sprint', glyph: '🚀' } })
    await show()
    const rush = panel().getByRole('button', { name: 'Rush' })
    expect(rush.querySelector('[data-icon]')?.textContent).toBe('🚀')
    expect(wordAfter(rush.querySelector('[data-icon]'))).toBe('Sprint')
    expect(rush.querySelector('.icon-inline')).toHaveClass('has-word')
  })

  it('reset button, no-cap value and clear-date mark follow the ledger', async () => {
    useIcons({ 'filter.reset': { glyph: '🧹' }, 'filter.no-cap': { word: 'endless' }, 'backlog.cli': { word: 'default' } })
    await show()
    const reset = panel().getByRole('button', { name: 'Reset to CLI defaults' })
    expect(painted(reset)).toBe('🧹 ⌨️Default')
    expect(document.querySelector('.panel .val .icon-word')?.textContent).toBe('Endless')
  })

  it('tier options and the keep check carry the tier icons and their words', async () => {
    useIcons({ 'tier.gold': { word: 'great' }, 'filter.proton-missing': { word: 'unrated' } })
    await show()
    const gold = [...document.querySelectorAll('.panel select option')].find((o) => o.getAttribute('aria-label') === 'gold')
    expect(gold?.textContent).toBe('🥇 Great')
    expect(wordAfter(document.querySelector('.panel .check [data-icon="filter.proton-missing"]'))).toBe('Unrated')
  })
})

describe('backlog icons: table', () => {
  it('sort arrow and column icons use their ids', async () => {
    useIcons({ 'backlog.sort-asc': { glyph: '🔼', word: 'up' }, 'basis.leisure': { word: 'slow' } })
    await show()
    const th = header('Leisure')
    expect(th).toHaveAttribute('aria-label', 'Leisure')
    expect(th.querySelector('[data-icon="backlog.sort-asc"]')?.textContent).toBe('🔼')
    expect([...th.querySelectorAll('.icon-word')].map((w) => w.textContent)).toEqual(['Slow', 'Up'])
  })

  it('tier cells, options and the no-data badge follow the ledger', async () => {
    useIcons({ 'tier.platinum': { glyph: '💠' }, 'keep.kept': { word: 'pinned' }, 'planner.no-data': { word: 'blank' } })
    history.replaceState(null, '', '/backlog/#nodata=1')
    await show([...GAMES, makeGame({ app_id: 9, name: 'No Data', rush_hours: -1, leisure_hours: -1, worst_hours: -1 })])
    expect(table().querySelector('td.proton [data-icon="tier.platinum"]')?.textContent).toBe('💠')
    const keep = screen.getByRole('combobox', { name: 'Filter Keep' })
    expect([...keep.querySelectorAll('option')].map((o) => o.textContent)).toContain('📌 Pinned')
    expect(wordAfter(table().querySelector('.badge [data-icon="planner.no-data"]'))).toBe('Blank')
  })

  it('number filter boxes keep their comparator placeholders', async () => {
    await show()
    expect(table().querySelector('input[aria-label$=" min"]')).toHaveAttribute('placeholder', '≥')
    expect(table().querySelector('input[aria-label$=" max"]')).toHaveAttribute('placeholder', '≤')
  })
})

describe('backlog icons: summary, glyph helpers and chart', () => {
  it('the banner and parity row paint ledger words and alternatives, spoken text unchanged', () => {
    useIcons({ 'filter.target-date': { word: 'deadline' }, 'summary.need': { glyph: '➡️' }, 'summary.match': { word: 'same' } })
    const filters = makeFilters({ targetDate: '2026-01-11' })
    const result = applyFilters(makeDataset([makeGame({ app_id: 1 })]), filters)
    const el = summaryCards(
      { result, filters, state: makeState(), presets: [2], defaultQualifying: result.remainingGames, paceVsHltb: makePaceVsHltb() },
      new Date('2026-01-01T00:00:00Z'),
    )
    document.body.append(el)
    expect(painted(el.querySelector('.target-banner'))).toContain('🏁Deadline')
    expect(painted(el.querySelector('.target-banner'))).toContain('➡️')
    expect(wordAfter(el.querySelector('.parity [data-icon="summary.match"]'))).toBe('Same')
    expect(el.querySelector('.target-banner')).toHaveTextContent('by')
  })

  it('style, tier and keep helpers draw ids, and the empty chart draws the empty id', () => {
    useIcons({ 'style.fast': { word: 'speedy' }, 'state.empty': { glyph: '📪' }, 'tier.bronze': { word: 'rough' } })
    const style = styleGlyph('faster_than_rush')
    expect(style.querySelector('.icon-word')?.textContent).toBe('Speedy')
    expect(style).toHaveTextContent('Faster than HLTB rush')
    expect(tierMarks('bronze').map((m) => (typeof m === 'string' ? m : m.textContent)).join('')).toBe('🥉Rough')
    expect(keepText('kept')).toBe('📌')
    expect(tierText('bronze / gold')).toBe('🥉 Rough/🥇')
    const filters = makeFilters()
    const box = timelineChart(applyFilters(makeDataset([]), filters), filters, makeState())
    expect(box.querySelector('.empty-icon')?.textContent).toBe('📪')
    expect(box).toHaveTextContent('Not enough games in scope to draw a timeline.')
  })
})
