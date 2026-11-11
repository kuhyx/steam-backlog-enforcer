// Guard test (textgate-rework R6): the backlog page paints glyphs, numbers and
// game names only; every label, hint and sentence is spoken only.

import { screen } from '@testing-library/dom'
import { afterEach, describe, expect, it } from 'vitest'
import { makeGame, makePaceVsHltb, makeState } from '../../test/factories'
import { flush, mount, stubApi } from '../../test/harness'
import { GAMES, panel, show } from '../../test/plannerHelpers'
import { visibleWords } from '../../test/visibleWords'
import { ANY_GLYPH, KEEP_GLYPH, styleGlyph, tierGlyphs } from './glyphs'
import { painted } from '../../test/painted'

afterEach(() => {
  history.replaceState(null, '', '/')
})

// <option> text paints only inside the open select; it is still checked here.
const NAMES = ['Alpha', 'Beta', 'Gamma', 'Hollow Knight', 'No Data']
// A unit right after a number is content (4 h/day, 140 days, 3 h).
const UNIT = /\d[\d,.]*\s*(h\/day|days?|[hmsd])\b/g
const words = (allowed: string[] = []) =>
  visibleWords(document.body, allowed).filter((w) => /[A-Za-z]{2,}/.test(w.replace(UNIT, '')))

describe('textgate guard: backlog', () => {
  it('the planner paints no words, with every panel open', async () => {
    history.replaceState(null, '', '/backlog/#nodata=1&proton=minTier&target=2099-01-01')
    await show([...GAMES, makeGame({ app_id: 9, name: 'No Data', rush_hours: -1, leisure_hours: -1, worst_hours: -1 })], {
      state: makeState({ current_game_name: 'Hollow Knight' }),
      pace_vs_hltb: makePaceVsHltb(),
    })
    expect(words(NAMES)).toEqual([])
  })

  it('the stats card paints no words', async () => {
    const summary = { qualifying: 4, rush_total: 1, leisure_total: 2, worst_total: 3 }
    stubApi({ 'GET /api/stats': { default_summary: summary, pace_vs_hltb: makePaceVsHltb() } })
    mount('<backlog-stats></backlog-stats>')
    await flush()
    expect(screen.getByRole('heading', { name: 'Estimates (default filters)' })).toBeInTheDocument()
    expect(words()).toEqual([])
  })

  it('the load error paints only the server message and the recovery command', async () => {
    stubApi({ 'GET /api/dataset': () => Promise.reject(new Error('net')) })
    mount('<game-table></game-table>')
    await flush()
    expect(visibleWords(document.body, ['net', './run.sh serve'])).toEqual([])
  })
})

describe('backlog glyphs', () => {
  it('paints ProtonDB tiers as medals, unknown tiers as ❔', () => {
    expect(tierGlyphs('gold / silver')).toBe('🥇/🥈')
    expect(tierGlyphs('—')).toBe('—')
    expect(tierGlyphs('')).toBe('—')
    expect(tierGlyphs('weird')).toBe('❔')
    expect(KEEP_GLYPH.excluded).toBe('🚫')
  })

  it('speaks an unknown play style by its key', () => {
    const el = styleGlyph('odd')
    expect(painted(el)).toBe('❔')
    expect(el).toHaveTextContent('odd')
    expect(el).toHaveClass('player-insight-style--odd')
  })

  it('offers glyph options in the table filters, values unchanged', async () => {
    await show()
    const keep = screen.getByRole('combobox', { name: 'Filter Keep' })
    expect([...keep.querySelectorAll('option')].map((o) => [o.value, o.textContent])).toContainEqual(['', ANY_GLYPH])
    expect([...keep.querySelectorAll('option')].map((o) => [o.value, o.textContent])).toContainEqual(['kept', '📌'])
    const tier = screen.getByRole('combobox', { name: 'Filter ProtonDB' })
    expect([...tier.querySelectorAll('option')].map((o) => o.textContent)).toContain('🥇/💎')
  })

  it('marks the pressed basis segment for assistive tech', async () => {
    await show()
    expect(panel().getByRole('button', { name: 'Leisure' })).toHaveAttribute('aria-pressed', 'true')
    expect(panel().getByRole('button', { name: 'Rush' })).toHaveAttribute('aria-pressed', 'false')
  })
})
