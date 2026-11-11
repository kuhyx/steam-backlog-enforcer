import { fireEvent } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeLibGame } from '../test/fixtures'
import { visibleWords } from '../test/visibleWords'
import { gameCard, paintCard, placeCard, type CardPaint } from './gameCard'

const PLAIN: CardPaint = { reason: null, selected: false, pickMode: false }

function make(over: Parameters<typeof makeLibGame>[0] = {}, paint: CardPaint = PLAIN) {
  const card = gameCard(makeLibGame({ app_id: 42, name: 'Hollow Knight', ...over }))
  paintCard(card, paint)
  document.body.append(card)
  return card
}

describe('gameCard', () => {
  it('is a button carrying its id, with title and meta line', () => {
    const card = make()
    expect(card).toHaveAttribute('type', 'button')
    expect(card).toHaveAttribute('data-app-id', '42')
    expect(card).toHaveTextContent('Hollow Knight')
    expect(card).toHaveTextContent('50%')
  })

  it('is placed with its index, as the roving tab stop or out of the tab order', () => {
    const card = make()
    expect(card).toHaveAttribute('tabindex', '-1')
    placeCard(card, 3, true)
    expect(card).toHaveAttribute('data-index', '3')
    expect(card).toHaveAttribute('tabindex', '0')
    placeCard(card, 4, false)
    expect(card).toHaveAttribute('tabindex', '-1')
  })

  it('exposes pressed state only in pick mode', () => {
    expect(make()).not.toHaveAttribute('aria-pressed')
  })

  it('exposes pressed and disabled in pick mode, with the reason shown', () => {
    const card = make({}, { pickMode: true, selected: true, reason: 'Already finished' })
    expect(card).toHaveAttribute('aria-pressed', 'true')
    expect(card).toHaveAttribute('aria-disabled', 'true')
    expect(card).toHaveClass('selected', 'ineligible')
    expect(card).toHaveTextContent('Already finished')
  })

  it('is not aria-disabled in pick mode when pickable', () => {
    const card = make({}, { pickMode: true, selected: false, reason: null })
    expect(card).not.toHaveAttribute('aria-disabled')
    expect(card).toHaveAttribute('aria-pressed', 'false')
  })

  it('repaints in place: reason updated, then removed, pick attributes dropped', () => {
    const card = make({}, { pickMode: true, selected: true, reason: 'A' })
    paintCard(card, { pickMode: true, selected: false, reason: 'B' })
    expect(card.querySelectorAll('.game-reason')).toHaveLength(1)
    expect(card).toHaveTextContent('B')
    paintCard(card, PLAIN)
    expect(card.querySelector('.game-reason')).toBeNull()
    expect(card).not.toHaveClass('selected')
    expect(card).not.toHaveClass('ineligible')
    expect(card).not.toHaveAttribute('aria-pressed')
    expect(card).not.toHaveAttribute('aria-disabled')
  })

  it('shows badges for assigned and installed', () => {
    const card = make({ assigned: true, installed: true })
    expect(card).toHaveTextContent('assigned')
    expect(card).toHaveTextContent('installed')
  })

  it('shows only the badge that applies', () => {
    const card = make({ installed: true })
    expect(card.querySelectorAll('.game-badges .pill')).toHaveLength(1)
    expect(card.querySelector('.game-badges .pill-neutral')).toHaveTextContent('💾installed')
    const assigned = make({ assigned: true })
    expect(assigned.querySelectorAll('.game-badges .pill')).toHaveLength(1)
    expect(assigned.querySelector('.game-badges .pill-accent')).toHaveTextContent('🎯assigned')
  })

  it('paints glyphs and numbers only; reasons and meta words are spoken', () => {
    const card = make({ assigned: true, installed: true }, { pickMode: true, selected: false, reason: 'Skipped until 2026-10-17' })
    expect(visibleWords(card, [card.querySelector('.game-title')?.textContent ?? ''])).toEqual([])
    expect(card.querySelector('.game-reason')).toHaveTextContent('⏭️ 2026-10-17')
  })

  it('has no badge row for a plain game', () => {
    expect(make().querySelector('.game-badges')).toBeNull()
  })

  it('lazy-loads the art and falls back to a title tile when it 404s', () => {
    const card = make()
    const img = card.getElementsByTagName('img')[0]
    expect(img).toHaveAttribute('src', '/api/art/42')
    expect(img).toHaveAttribute('loading', 'lazy')
    fireEvent.error(img)
    expect(card.querySelector('img')).toBeNull()
    expect(card.querySelector('.cover-tile')).toHaveTextContent('Hollow Knight')
  })
})
