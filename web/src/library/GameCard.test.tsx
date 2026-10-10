import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeLibGame } from '../test/fixtures'
import { GameCard } from './GameCard'

function renderCard(over: Partial<React.ComponentProps<typeof GameCard>> = {}) {
  const onActivate = vi.fn()
  const props = {
    game: makeLibGame({ app_id: 42, name: 'Hollow Knight' }),
    index: 3,
    reason: null,
    selected: false,
    focusable: true,
    pickMode: false,
    onActivate,
    ...over,
  }
  render(<GameCard {...props} />)
  return { onActivate, card: screen.getByRole('button') }
}

describe('GameCard', () => {
  it('is a button carrying its id and index, with title and meta line', () => {
    const { card } = renderCard()
    expect(card).toHaveAttribute('data-app-id', '42')
    expect(card).toHaveAttribute('data-index', '3')
    expect(card).toHaveTextContent('Hollow Knight')
    expect(card).toHaveTextContent('50%')
  })

  it('is a roving tab stop', () => {
    expect(renderCard().card).toHaveAttribute('tabindex', '0')
  })

  it('is out of the tab order when not the active card', () => {
    expect(renderCard({ focusable: false }).card).toHaveAttribute('tabindex', '-1')
  })

  it('exposes pressed state only in pick mode', () => {
    expect(renderCard().card).not.toHaveAttribute('aria-pressed')
  })

  it('exposes pressed and disabled in pick mode, with the reason shown', () => {
    const { card } = renderCard({ pickMode: true, selected: true, reason: 'Already finished' })
    expect(card).toHaveAttribute('aria-pressed', 'true')
    expect(card).toHaveAttribute('aria-disabled', 'true')
    expect(card).toHaveClass('selected', 'ineligible')
    expect(card).toHaveTextContent('Already finished')
  })

  it('is not aria-disabled in pick mode when pickable', () => {
    const { card } = renderCard({ pickMode: true })
    expect(card).not.toHaveAttribute('aria-disabled')
    expect(card).toHaveAttribute('aria-pressed', 'false')
  })

  it('shows badges for assigned and installed', () => {
    const { card } = renderCard({ game: makeLibGame({ assigned: true, installed: true }) })
    expect(card).toHaveTextContent('assigned')
    expect(card).toHaveTextContent('installed')
  })

  it('shows only the badge that applies, and none otherwise', () => {
    renderCard({ game: makeLibGame({ installed: true }) })
    expect(screen.getByText('installed')).toBeInTheDocument()
    expect(screen.queryByText('assigned')).toBeNull()
  })

  it('has no badge row for a plain game', () => {
    renderCard()
    expect(document.querySelector('.game-badges')).toBeNull()
  })

  it('reports clicks', async () => {
    const { card, onActivate } = renderCard()
    await userEvent.click(card)
    expect(onActivate).toHaveBeenCalledTimes(1)
  })

  it('lazy-loads the art and falls back to a title tile when it 404s', () => {
    const { card } = renderCard()
    const img = card.querySelector('img')!
    expect(img).toHaveAttribute('src', '/api/art/42')
    expect(img).toHaveAttribute('loading', 'lazy')
    fireEvent.error(img)
    expect(card.querySelector('img')).toBeNull()
    expect(card.querySelector('.cover-tile')).toHaveTextContent('Hollow Knight')
  })
})
