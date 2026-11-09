// The `<game-browser>` toolbar: search box, sort, filter checkboxes and the
// result count. It is built once and never rebuilt, so typing keeps its
// caret; the browser only writes values into it and hears every edit back.

import type { LibraryGame } from '../api/contract'
import { h } from '../lib/dom'
import { FILTERS, type BrowserState } from './browserState'
import { SearchBox, type SearchBoxOptions } from './searchBox'
import { SORTS, type Filters, type SortKey } from './view'

export interface ToolbarOptions extends SearchBoxOptions {
  onSort: (sort: SortKey) => void
  onFilter: (key: keyof Filters, on: boolean) => void
}

export class BrowserToolbar {
  readonly el: HTMLElement
  private readonly searchBox: SearchBox
  private readonly sortSelect: HTMLSelectElement
  private readonly checks: Map<keyof Filters, HTMLInputElement>
  private readonly count = h('span', { class: 'muted lib-count', 'aria-live': 'polite' })

  constructor(opts: ToolbarOptions) {
    this.searchBox = new SearchBox(opts)
    this.sortSelect = h(
      'select',
      {
        class: 'input',
        onchange: () => {
          opts.onSort(this.sortSelect.value as SortKey)
        },
      },
      SORTS.map((s) => h('option', { value: s.key }, s.label)),
    )
    this.checks = new Map(
      FILTERS.map(([key]) => [
        key,
        h('input', {
          type: 'checkbox',
          onchange: (e: Event) => {
            opts.onFilter(key, (e.target as HTMLInputElement).checked)
          },
        }),
      ]),
    )
    this.el = h(
      'div',
      { class: 'lib-toolbar' },
      this.searchBox.el,
      h('label', { class: 'lib-sort' }, h('span', { class: 'field-label' }, 'Sort'), this.sortSelect),
      h(
        'fieldset',
        { class: 'lib-filters' },
        h('legend', { class: 'sr-only' }, 'Filters'),
        FILTERS.map(([key, label]) => h('label', { class: 'check' }, this.checks.get(key), label)),
      ),
      this.count,
    )
  }

  /** Put `s` into the controls (a reload, or the hash edited by hand). */
  applyState(s: BrowserState): void {
    if (this.searchBox.value !== s.query) this.searchBox.value = s.query
    this.sortSelect.value = s.sort
    for (const [key, box] of this.checks) box.checked = s.filters[key]
  }

  /** A search ranks by relevance, so the sort is off while there is one. */
  lockSort(locked: boolean): void {
    this.sortSelect.disabled = locked
  }

  setSuggestions(games: LibraryGame[]): void {
    this.searchBox.setSuggestions(games)
  }

  setCount(text: string): void {
    this.count.textContent = text
  }
}
