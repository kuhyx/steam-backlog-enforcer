// One tile of the library grid (was GameCard.tsx). Built once per game and
// reused across searches, so a keystroke never recreates a cover <img>;
// `paintCard` updates the parts that depend on the browser's state.

import { ENDPOINTS, type LibraryGame } from '../api/contract'
import { h } from '../lib/dom'
import { metaLine } from './view'

export interface CardPaint {
  /** Why it cannot be picked here, or null. Greys the card out. */
  reason: string | null
  selected: boolean
  pickMode: boolean
}

/** Portrait cover, lazily loaded; a title tile when the server has none. */
function cover(game: LibraryGame): HTMLImageElement {
  const img = h('img', { class: 'cover', src: ENDPOINTS.art(game.app_id), alt: '', loading: 'lazy', decoding: 'async' })
  img.addEventListener(
    'error',
    () => {
      img.replaceWith(h('div', { class: 'cover cover-tile', 'aria-hidden': 'true' }, h('span', {}, game.name)))
    },
    { once: true },
  )
  return img
}

/**
 * A button in both modes so it is a focus stop; in browse mode it only takes
 * focus, in pick mode it selects. Clicks are handled by the grid.
 */
export function gameCard(game: LibraryGame): HTMLButtonElement {
  return h(
    'button',
    { type: 'button', class: 'game-card', 'data-app-id': game.app_id, tabindex: -1 },
    cover(game),
    h('span', { class: 'game-title' }, game.name),
    h('span', { class: 'game-meta' }, metaLine(game)),
    game.assigned || game.installed
      ? h(
          'span',
          { class: 'game-badges' },
          game.assigned ? h('span', { class: 'pill pill-accent' }, 'assigned') : null,
          game.installed ? h('span', { class: 'pill pill-neutral' }, 'installed') : null,
        )
      : null,
  )
}

/** Apply pick state: selection, eligibility and the reason line. */
export function paintCard(card: HTMLButtonElement, { reason, selected, pickMode }: CardPaint): void {
  card.classList.toggle('ineligible', reason !== null)
  card.classList.toggle('selected', selected)
  if (pickMode) card.setAttribute('aria-pressed', String(selected))
  else card.removeAttribute('aria-pressed')
  if (pickMode && reason !== null) card.setAttribute('aria-disabled', 'true')
  else card.removeAttribute('aria-disabled')
  let line = card.querySelector('.game-reason')
  if (reason === null) {
    line?.remove()
    return
  }
  line ??= card.appendChild(h('span', { class: 'game-reason' }))
  line.textContent = reason
}

/** Place the card in the grid: its position and whether it is the tab stop. */
export function placeCard(card: HTMLButtonElement, index: number, focusable: boolean): void {
  card.dataset.index = String(index)
  card.tabIndex = focusable ? 0 : -1
}
