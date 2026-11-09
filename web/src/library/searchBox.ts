// Library search (was SearchBox.tsx): an ARIA combobox. Typing filters the
// grid behind it and lists the top suggestions; ↑/↓ move through them, Enter
// chooses the highlighted one (or the first), Escape closes the list, then
// clears. The input is built once; only the list and ARIA state change.

import type { LibraryGame } from '../api/contract'
import { h } from '../lib/dom'
import { uid } from '../lib/ids'
import { metaLine } from './view'

export interface SearchBoxOptions {
  /** Every edit of the text (typing, or Escape clearing it). */
  onInput: (value: string) => void
  onChoose: (game: LibraryGame) => void
  /** Why a game cannot be picked here (pick mode differs from the library). */
  reason: (game: LibraryGame) => string | null
}

export class SearchBox {
  readonly el: HTMLDivElement
  readonly input: HTMLInputElement
  private readonly list: HTMLUListElement
  private readonly listId = uid('lib-suggest')
  private readonly opts: SearchBoxOptions
  private suggestions: LibraryGame[] = []
  private open = false
  private active = -1

  constructor(opts: SearchBoxOptions) {
    this.opts = opts
    this.input = h('input', {
      class: 'input',
      type: 'search',
      role: 'combobox',
      'aria-label': 'Search your games',
      'aria-expanded': 'false',
      'aria-controls': this.listId,
      'aria-autocomplete': 'list',
      placeholder: 'Search your games (typos are fine)…',
    })
    this.list = h('ul', { id: this.listId, role: 'listbox', class: 'lib-suggest', hidden: true, 'aria-label': 'Suggestions' })
    this.el = h('div', { class: 'lib-search' }, this.input, this.list)
    this.input.addEventListener('input', () => {
      this.open = true
      this.active = -1
      opts.onInput(this.input.value)
      this.render()
    })
    this.input.addEventListener('focus', () => {
      this.open = true
      this.render()
    })
    this.input.addEventListener('blur', () => {
      this.open = false
      this.render()
    })
    this.input.addEventListener('keydown', (e) => {
      this.onKeyDown(e)
    })
  }

  get value(): string {
    return this.input.value
  }

  /** Set the text without reporting it (restoring state from the URL). */
  set value(v: string) {
    this.input.value = v
    this.render()
  }

  setSuggestions(games: LibraryGame[]): void {
    this.suggestions = games
    this.render()
  }

  private get shown(): boolean {
    return this.open && this.input.value.trim() !== '' && this.suggestions.length > 0
  }

  private choose(game: LibraryGame): void {
    this.open = false
    this.active = -1
    this.render()
    this.opts.onChoose(game)
  }

  private onKeyDown(e: KeyboardEvent): void {
    const n = this.suggestions.length
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (n === 0) return
      e.preventDefault()
      this.open = true
      const step = e.key === 'ArrowDown' ? 1 : -1
      this.active = this.active < 0 && step < 0 ? n - 1 : (this.active + step + n) % n
      this.render()
    } else if (e.key === 'Enter') {
      if (!this.shown) return
      e.preventDefault()
      // The highlighted suggestion, else the first.
      this.choose(this.suggestions[this.active >= 0 && this.active < n ? this.active : 0])
    } else if (e.key === 'Escape') {
      if (this.shown) {
        e.preventDefault()
        e.stopPropagation()
        this.open = false
        this.render()
      } else if (this.input.value) {
        e.preventDefault()
        e.stopPropagation()
        this.input.value = ''
        this.opts.onInput('')
        this.render()
      }
    }
  }

  private render(): void {
    const shown = this.shown
    this.input.setAttribute('aria-expanded', String(shown))
    if (shown && this.active >= 0) this.input.setAttribute('aria-activedescendant', `${this.listId}-${this.active}`)
    else this.input.removeAttribute('aria-activedescendant')
    this.list.hidden = !shown
    this.list.replaceChildren(
      ...(shown
        ? this.suggestions.map((g, i) =>
            h(
              'li',
              {
                id: `${this.listId}-${i}`,
                role: 'option',
                'aria-selected': String(i === this.active),
                class: i === this.active ? 'lib-suggest-item active' : 'lib-suggest-item',
                // mousedown, not click: the input's blur would close the list first.
                onmousedown: (e: Event) => {
                  e.preventDefault()
                  this.choose(g)
                },
              },
              h('span', { class: 'lib-suggest-name' }, g.name),
              h('span', { class: 'lib-suggest-meta' }, this.opts.reason(g) ?? metaLine(g)),
            ),
          )
        : []),
    )
  }
}
