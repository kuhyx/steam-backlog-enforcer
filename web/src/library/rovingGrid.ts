// The `<game-browser>` cover grid as one tab stop: arrows, PageUp/PageDown
// and Home/End move between cards (roving tabindex). It also holds a card
// to focus until the grid, which trails the search box by a frame, shows it.

import { h } from '../lib/dom'
import { placeCard } from './gameCard'

/** Grid columns as laid out right now (for ↑/↓ moving one row). */
function columns(grid: HTMLElement): number {
  return Math.max(1, getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length)
}

export class RovingGrid {
  readonly el = h('div', {
    class: 'game-grid',
    role: 'group',
    'aria-label': 'Games',
    onkeydown: (e: Event) => {
      this.onKey(e as KeyboardEvent)
    },
  })
  private active = 0
  /** A card to focus once the grid shows it. */
  private focusId: number | null = null

  /** Show `cards` in this order, keeping the tab stop at the same position. */
  show(cards: HTMLButtonElement[]): void {
    // A refetch replaces every card: keep focus on the same game.
    const focused = document.activeElement
    if (focused instanceof HTMLElement && focused.parentElement === this.el) this.focusId ??= Number(focused.dataset.appId)
    const current = Math.min(this.active, Math.max(0, cards.length - 1))
    cards.forEach((card, i) => {
      placeCard(card, i, i === current)
    })
    this.el.replaceChildren(...cards)
    this.applyFocus()
  }

  /** Focus the card of `appId` now, or once the grid shows it. */
  focusGame(appId: number): void {
    this.focusId = appId
    this.applyFocus()
  }

  /** Make `card` the grid's one tab stop. */
  setActive(card: HTMLElement): void {
    for (const c of this.el.querySelectorAll<HTMLElement>('[tabindex="0"]')) c.tabIndex = -1
    card.tabIndex = 0
    this.active = Number(card.dataset.index)
  }

  /** Focus the pending card if the grid shows it yet. */
  private applyFocus(): void {
    if (this.focusId === null) return
    const card = this.el.querySelector<HTMLElement>(`[data-app-id="${this.focusId}"]`)
    if (!card) return
    this.focusId = null
    this.setActive(card)
    card.focus()
  }

  private onKey(e: KeyboardEvent): void {
    const cards = [...this.el.children] as HTMLElement[]
    const cols = columns(this.el)
    const page = cols * 3
    const moves: Partial<Record<string, number>> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: cols,
      ArrowUp: -cols,
      PageDown: page,
      PageUp: -page,
      Home: -Infinity,
      End: Infinity,
    }
    const move = moves[e.key]
    if (move === undefined || cards.length === 0) return
    e.preventDefault()
    const current = Math.min(this.active, cards.length - 1)
    const next = Math.min(cards.length - 1, Math.max(0, current + move))
    const card = cards[next]
    this.setActive(card)
    card.focus()
  }
}
