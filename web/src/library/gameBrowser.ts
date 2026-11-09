// `<game-browser [hash-state]>` (was GameBrowser.tsx): every owned game as a
// cover grid, with fuzzy search + suggestions, sort and filters. The
// toolbar (browserToolbar.ts) and the keyboard-driven grid (rovingGrid.ts)
// are built once; this element owns the state and decides what they show.
//
// A keystroke runs the search synchronously (suggestions, count) and the
// grid follows on the next animation frame, as useDeferredValue did: fast
// typing coalesces into one grid update. Cards are built once per library
// load and reused, so no cover <img> is ever recreated by a search.
//
// `pick` (see pick.ts) puts it in pick mode for a job's game prompt. With
// `hash-state` its state lives in the URL hash (see browserState.ts).

import type { LibraryGame } from '../api/contract'
import { q } from '../api/queries'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { errorNotice, loading } from '../ui/build'
import { stateFromHash, stateToHash, type BrowserState } from './browserState'
import { BrowserToolbar } from './browserToolbar'
import { buildIndex, search, type Searchable } from './fuzzy'
import { gameCard, paintCard, type CardPaint } from './gameCard'
import { writeHash } from './hashState'
import type { GameBrowserElement, PickMode } from './pick'
import { RovingGrid } from './rovingGrid'
import { filterGames, NO_FILTERS, sortGames } from './view'

const SUGGESTIONS = 8

interface Built {
  game: LibraryGame
  card: HTMLButtonElement
}

export class GameBrowser extends LiveElement implements GameBrowserElement {
  private pickMode: PickMode | null = null
  private built = false
  private state: BrowserState = { query: '', sort: 'name', filters: { ...NO_FILTERS } }
  private frame: number | null = null
  private visible: LibraryGame[] = []
  private indexOf: readonly LibraryGame[] | null = null
  private index = new Map<number, Searchable>()
  private cardsOf: readonly LibraryGame[] | null = null
  private cards = new Map<number, Built>()

  private readonly toolbar = new BrowserToolbar({
    onInput: (value) => {
      this.state.query = value
      this.changed()
    },
    onChoose: (game) => {
      this.choose(game)
    },
    reason: (game) => this.reason(game),
    onSort: (sort) => {
      this.state.sort = sort
      this.changed()
    },
    onFilter: (key, on) => {
      this.state.filters = { ...this.state.filters, [key]: on }
      this.changed()
    },
  })
  private readonly notices = h('div', { class: 'contents' })
  private readonly none = h('div', { class: 'contents' })
  private readonly grid = new RovingGrid()

  constructor() {
    super()
    // `browser.pick = …` before this tag was defined left an own property
    // that would shadow the accessor: move it through the setter.
    if (Object.hasOwn(this, 'pick')) {
      const early = (this as { pick: PickMode | null }).pick
      Reflect.deleteProperty(this, 'pick')
      this.pick = early
    }
  }

  get pick(): PickMode | null {
    return this.pickMode
  }

  /** Same `appIds` with a new `selected` only moves the highlight. */
  set pick(next: PickMode | null) {
    const prev = this.pickMode
    this.pickMode = next
    if (prev && prev.appIds === next?.appIds) {
      for (const id of [prev.selected, next.selected]) {
        const built = id === null ? undefined : this.cards.get(id)
        if (built) paintCard(built.card, this.paintOf(built.game))
      }
      return
    }
    this.cards = new Map()
    if (this.built) this.refresh()
  }

  protected override setup(): void {
    if (!this.built) {
      this.built = true
      this.classList.add('lib')
      if (this.hashState) this.applyState(stateFromHash())
      this.replaceChildren(this.toolbar.el, this.notices, this.none, this.grid.el)
    }
    this.watch(q.library)
    if (this.hashState) {
      const onHash = () => {
        this.applyState(stateFromHash())
        this.refresh()
      }
      window.addEventListener('hashchange', onHash)
      this.onCleanup(() => {
        window.removeEventListener('hashchange', onHash)
      })
    }
    this.onCleanup(() => {
      if (this.frame !== null) cancelAnimationFrame(this.frame)
      this.frame = null
    })
  }

  protected update(): void {
    const { data, error } = q.library.state
    this.notices.replaceChildren(...(error ? [errorNotice(error)] : data ? [] : [loading('your library')]))
    this.refresh()
  }

  private get hashState(): boolean {
    return this.hasAttribute('hash-state')
  }

  /** Adopt `s` and show it in the toolbar (a reload, or the hash edited by hand). */
  private applyState(s: BrowserState): void {
    this.state = s
    this.toolbar.applyState(s)
  }

  private changed(): void {
    if (this.hashState) writeHash(stateToHash(this.state))
    this.refresh()
  }

  /** Why `g` cannot be picked here, or null. */
  private reason(g: LibraryGame): string | null {
    const pick = this.pickMode
    if (!pick) return g.ineligible_reason
    return pick.appIds.has(g.app_id) ? null : (g.ineligible_reason ?? 'Not offered here')
  }

  private paintOf(g: LibraryGame): CardPaint {
    return { reason: this.reason(g), selected: this.pickMode?.selected === g.app_id, pickMode: this.pickMode !== null }
  }

  /** Recompute the visible games and suggestions now; the grid follows next frame. */
  private refresh(): void {
    const query = this.state.query.trim()
    this.toolbar.lockSort(query !== '')
    const games = q.library.state.data?.games
    if (!games) return
    if (this.indexOf !== games) {
      this.indexOf = games
      this.index = buildIndex(games)
    }
    const filtered = filterGames(games, this.state.filters, (g) => this.reason(g) === null)
    this.visible = query ? search(filtered, this.index, this.state.query) : sortGames(filtered, this.state.sort)
    this.toolbar.setSuggestions(query ? this.visible.slice(0, SUGGESTIONS) : [])
    this.frame ??= requestAnimationFrame(() => {
      this.frame = null
      this.renderGrid(games)
    })
  }

  private card(g: LibraryGame): HTMLButtonElement {
    let built = this.cards.get(g.app_id)
    if (!built) {
      const card = gameCard(g)
      card.addEventListener('click', () => {
        this.activate(card, g)
      })
      paintCard(card, this.paintOf(g))
      built = { game: g, card }
      this.cards.set(g.app_id, built)
    }
    return built.card
  }

  private renderGrid(games: readonly LibraryGame[]): void {
    if (this.cardsOf !== games) {
      this.cardsOf = games
      this.cards = new Map()
    }
    this.grid.show(this.visible.map((g) => this.card(g)))
    const query = this.state.query.trim()
    this.toolbar.setCount(`${this.visible.length} of ${games.length} games${query ? ' · by relevance' : ''}`)
    this.none.replaceChildren(...(this.visible.length === 0 ? [h('p', { class: 'muted' }, 'No game matches.')] : []))
  }

  /** A click: becomes the tab stop; in pick mode an eligible card is selected. */
  private activate(card: HTMLButtonElement, g: LibraryGame): void {
    this.grid.setActive(card)
    // Select only: assigning can uninstall other games, so it takes the
    // prompt's explicit "Pick …" button, never a double-click.
    if (this.pickMode && this.reason(g) === null) this.pickMode.onSelect(g.app_id)
  }

  /** A suggestion chosen: select it if pickable, and move focus to its card. */
  private choose(g: LibraryGame): void {
    if (this.pickMode && this.reason(g) === null) this.pickMode.onSelect(g.app_id)
    this.grid.focusGame(g.app_id)
  }
}

define('game-browser', GameBrowser)
