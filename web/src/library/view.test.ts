import { describe, expect, it } from 'vitest'
import { h, type Child } from '../lib/dom'
import { makeLibGame } from '../test/fixtures'
import { useIcons } from '../test/iconLedger'
import { completion, filterGames, isCompleted, metaGlyphs, metaLine, NO_FILTERS, reasonGlyph, reasonOrMeta, sortGames } from './view'

const g = makeLibGame

describe('completion', () => {
  it('is a percentage, or null without achievements', () => {
    expect(completion(g({ achievements_total: 8, achievements_unlocked: 2 }))).toBe(25)
    expect(completion(g({ achievements_total: 0 }))).toBeNull()
  })

  it('isCompleted needs achievements and all of them', () => {
    expect(isCompleted(g({ achievements_total: 4, achievements_unlocked: 4 }))).toBe(true)
    expect(isCompleted(g({ achievements_total: 4, achievements_unlocked: 3 }))).toBe(false)
    expect(isCompleted(g({ achievements_total: 0, achievements_unlocked: 0 }))).toBe(false)
  })
})

describe('sortGames', () => {
  const a = g({ app_id: 1, name: 'Bravo', last_played: 100, hltb_hours: 30, achievements_unlocked: 1 })
  const b = g({ app_id: 2, name: 'Alpha', last_played: 200, hltb_hours: 5, achievements_unlocked: 9 })
  const c = g({ app_id: 3, name: 'Charlie', last_played: null, hltb_hours: null, achievements_total: 0 })
  const d = g({ app_id: 4, name: 'Delta', last_played: null, hltb_hours: null, achievements_total: 0 })
  const names = (key: Parameters<typeof sortGames>[1]) => sortGames([c, a, d, b], key).map((x) => x.name)

  it('sorts by name', () => { expect(names('name')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']); })
  it('sorts recent first, never-played last', () => { expect(names('recent')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']); })
  it('sorts by completion descending, unknown last', () => { expect(names('completion')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']); })
  it('sorts shortest HLTB first, unknown last', () => { expect(names('hltb')).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']); })

  it('does not mutate its input', () => {
    const input = [b, a]
    sortGames(input, 'name')
    expect(input).toEqual([b, a])
  })
})

describe('filterGames', () => {
  const done = g({ app_id: 1, achievements_total: 2, achievements_unlocked: 2, installed: true })
  const open = g({ app_id: 2, installed: false })
  const all = [done, open]
  const pickable = (x: { app_id: number }) => x.app_id === 2

  it('keeps everything without filters', () => {
    expect(filterGames(all, NO_FILTERS, pickable)).toEqual(all)
  })
  it('hides completed', () => {
    expect(filterGames(all, { ...NO_FILTERS, hideCompleted: true }, pickable)).toEqual([open])
  })
  it('keeps installed only', () => {
    expect(filterGames(all, { ...NO_FILTERS, installedOnly: true }, pickable)).toEqual([done])
  })
  it('keeps pickable only', () => {
    expect(filterGames(all, { ...NO_FILTERS, pickableOnly: true }, pickable)).toEqual([open])
  })
})

describe('metaLine', () => {
  it('joins percentage, HLTB and playtime', () => {
    expect(metaLine(g({ achievements_total: 8, achievements_unlocked: 3, hltb_hours: 12, playtime_minutes: 192 })))
      .toBe('37% · 12 h HLTB · 3.2 h played')
  })
  it('uses one decimal under 10 h', () => {
    expect(metaLine(g({ hltb_hours: 4.25, playtime_minutes: 0 }))).toBe('50% · 4.3 h HLTB')
  })
  it('says so without achievements, HLTB or playtime', () => {
    expect(metaLine(g({ achievements_total: 0, hltb_hours: null, playtime_minutes: 0 }))).toBe('No achievements')
  })
})

/** The text the painted nodes show. */
const text = (nodes: Child[]) => h('span', {}, ...nodes).textContent

describe('metaGlyphs', () => {
  it('paints trophy, clock and play with their values', () => {
    expect(text(metaGlyphs(g({ achievements_total: 8, achievements_unlocked: 3, hltb_hours: 12, playtime_minutes: 192 }))))
      .toBe('🏆 37% · ⏱️ 12 h · ▶️ 3.2 h')
  })
  it('paints a dash for no achievements and drops unknown HLTB and zero playtime', () => {
    expect(text(metaGlyphs(g({ achievements_total: 0, hltb_hours: null, playtime_minutes: 0 })))).toBe('🏆 —')
  })
  it('draws the user word right of each icon and his alternative glyph', () => {
    useIcons({ 'lib.hltb': { word: 'length', glyph: '⌛' }, 'lib.completion': { word: 'percent' } })
    const meta = h('span', {}, ...metaGlyphs(g({ achievements_total: 8, achievements_unlocked: 3, hltb_hours: 12, playtime_minutes: 0 })))
    expect([...meta.querySelectorAll('.icon-word')].map((w) => w.textContent)).toEqual(['Percent', 'Length'])
    expect(meta.querySelector('[data-icon="lib.hltb"]')?.textContent).toBe('⌛')
    expect(meta.querySelector('[data-icon="lib.hltb"]')?.nextElementSibling).toHaveClass('icon-word')
  })
})

describe('reasonGlyph', () => {
  it.each([
    ['Already 100% complete', '🏆✅'],
    ['No achievements', '🏆🚫'],
    ['Skipped by you', '⏭️'],
    ['Skipped until 2026-09-01', '⏭️ 2026-09-01'],
    ['Something else', '⛔'],
    ['Blocked until 2026-10-02', '⛔ 2026-10-02'],
  ])('%s paints %s', (reason, painted) => {
    expect(text(reasonGlyph(reason))).toBe(painted)
  })
  it('draws the user word beside the reason icon, the date after it', () => {
    useIcons({ 'lib.why.skipped': { word: 'skipped' } })
    const el = h('span', {}, ...reasonGlyph('Skipped until 2026-09-01'))
    expect(el.textContent).toBe('⏭️Skipped 2026-09-01')
  })
})

describe('reasonOrMeta', () => {
  it('paints the meta glyphs and speaks the meta line when pickable', () => {
    const game = g({ achievements_total: 8, achievements_unlocked: 3, hltb_hours: 12, playtime_minutes: 192 })
    const el = reasonOrMeta(null, game, 'sub')
    expect(el.className).toBe('sub')
    expect(el.querySelector('[aria-hidden="true"]')?.textContent).toBe(text(metaGlyphs(game)))
    expect(el.querySelector('.sr-only')?.textContent).toBe(metaLine(game))
  })
  it('paints the reason glyph and speaks the reason when not pickable', () => {
    const el = reasonOrMeta('No achievements', g(), 'sub')
    expect(el.querySelector('[aria-hidden="true"]')?.textContent).toBe('🏆🚫')
    expect(el.querySelector('.sr-only')?.textContent).toBe('No achievements')
  })
})
