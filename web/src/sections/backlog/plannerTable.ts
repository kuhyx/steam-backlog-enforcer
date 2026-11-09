// The planner's game table (was GameTable.tsx): sortable headers, a
// per-column filter row, the search box and one row per game. Rows are
// built once per game and repainted in place; the planner owns the sort and
// filter state (tableState.ts) and passes it into every `show()`.

import type { GameRow } from '../../estimate'
import { fmtHoursPrecise, fmtPlaytime } from '../../format'
import { h } from '../../lib/dom'
import { tierLabel } from '../../protondb'
import type { WebGame } from '../../types'
import { COLUMNS, optionsFor, type Column, type ColumnKey, type TableState } from './tableState'

export const DISPLAY_CAP = 300

export interface PlannerTableOptions {
  onSort: (key: ColumnKey) => void
  /** A column filter edited; `id` is `<col>` or `<col>.min|max`, `value` '' when cleared. */
  onColumnFilter: (id: string, value: string) => void
  onSearch: (value: string) => void
  onToggle: (appId: number) => void
}

interface RowEls {
  tr: HTMLTableRowElement
  name: HTMLTableCellElement
  link: HTMLAnchorElement
  badge: HTMLSpanElement
  cells: HTMLTableCellElement[]
  keep: HTMLInputElement
}

export function hltbUrl(game: WebGame): string {
  if (game.hltb_game_id > 0) return `https://howlongtobeat.com/game/${game.hltb_game_id}`
  return `https://howlongtobeat.com/?q=${encodeURIComponent(game.name)}`
}

const optionLabel = (c: Column, v: string) => (c.key === 'keep' ? (v === 'kept' ? 'Kept' : 'Excluded') : v)

export class PlannerTable {
  readonly el: HTMLElement
  private readonly opts: PlannerTableOptions
  private readonly count = h('h2')
  private readonly search = h('input', { type: 'search', placeholder: 'Search games…', 'aria-label': 'Search games' })
  private readonly heads: [Column, HTMLTableCellElement, HTMLButtonElement][] = []
  private readonly inputs = new Map<string, HTMLInputElement | HTMLSelectElement>()
  private readonly selects: [Column, HTMLSelectElement][] = []
  private readonly tbody = h('tbody')
  private readonly overflow = h('p', { class: 'hint' })
  private readonly rows = new Map<number, RowEls>()

  constructor(opts: PlannerTableOptions) {
    this.opts = opts
    this.search.addEventListener('input', () => {
      opts.onSearch(this.search.value)
    })
    this.el = this.build()
  }

  /** Write the search text and every column filter into their inputs. */
  syncInputs(search: string, filters: ReadonlyMap<string, string>): void {
    this.search.value = search
    for (const [id, input] of this.inputs) input.value = filters.get(id) ?? ''
  }

  /** Show `visible` (capped) under headers and filters matching `table`; `all` feeds the select options. */
  show(all: readonly GameRow[], visible: readonly GameRow[], table: TableState): void {
    this.syncOptions(all, table)
    this.syncHeads(table)
    this.count.textContent = `Games (${visible.length})`
    const trs = visible.slice(0, DISPLAY_CAP).map((r) => this.rowFor(r))
    const current = this.tbody.children
    // Re-order only when the order changed: moving a row would blur its checkbox.
    if (trs.length !== current.length || trs.some((tr, i) => current[i] !== tr)) this.tbody.replaceChildren(...trs)
    this.overflow.hidden = visible.length <= DISPLAY_CAP
    this.overflow.textContent = `Showing first ${DISPLAY_CAP} of ${visible.length}. Use search to narrow.`
  }

  private build(): HTMLElement {
    const filterCell = (c: Column): HTMLTableCellElement => {
      const field = (id: string, el: HTMLInputElement | HTMLSelectElement) => {
        this.inputs.set(id, el)
        el.addEventListener(el instanceof HTMLSelectElement ? 'change' : 'input', () => {
          this.opts.onColumnFilter(id, el.value)
        })
        return el
      }
      if (c.filter === 'range') {
        const bound = (side: 'min' | 'max') =>
          field(`${c.key}.${side}`, h('input', { type: 'number', inputmode: 'decimal', placeholder: side, 'aria-label': `${c.label} ${side}` }))
        return h('td', { class: 'range-filter' }, h('div', {}, bound('min'), bound('max')))
      }
      if (c.filter === 'select') {
        const select = h('select', { 'aria-label': `Filter ${c.label}` }, h('option', { value: '' }, 'All'))
        this.selects.push([c, select])
        return h('td', {}, field(c.key, select))
      }
      return h('td', {}, field(c.key, h('input', { type: 'search', placeholder: 'Filter…', 'aria-label': `Filter ${c.label}` })))
    }
    const headCell = (c: Column): HTMLTableCellElement => {
      const button = h('button', { type: 'button', class: 'sort-btn' }, c.label)
      const th = h('th', { class: c.numeric ? 'num clickable' : 'clickable', scope: 'col' }, button)
      th.addEventListener('click', () => {
        this.opts.onSort(c.key)
      })
      this.heads.push([c, th, button])
      return th
    }
    return h(
      'div',
      { class: 'table-wrap' },
      h('div', { class: 'table-head' }, this.count, this.search),
      h(
        'div',
        { class: 'table-scroll' },
        h(
          'table',
          {},
          h(
            'thead',
            {},
            h('tr', {}, COLUMNS.map(headCell)),
            h('tr', { class: 'filter-row' }, COLUMNS.map(filterCell)),
          ),
          this.tbody,
        ),
      ),
      this.overflow,
    )
  }

  private rowFor(r: GameRow): HTMLTableRowElement {
    const id = r.game.app_id
    let row = this.rows.get(id)
    if (!row) {
      const cells = Array.from({ length: 7 }, (_, i) => h('td', { class: i === 6 ? 'num proton' : 'num' }))
      const keep = h('input', { type: 'checkbox' })
      keep.addEventListener('change', () => { this.opts.onToggle(id) })
      const link = h('a', { target: '_blank', rel: 'noreferrer' })
      const name = h('td', { class: 'name' }, link)
      row = { tr: h('tr', {}, name, cells, h('td', { class: 'num' }, keep)), name, link, badge: h('span', { class: 'badge' }, 'no data'), cells, keep }
      this.rows.set(id, row)
    }
    const g = r.game
    row.tr.className = r.excluded ? 'excluded' : ''
    row.link.href = hltbUrl(g)
    row.link.textContent = g.name
    if (r.noData) row.name.append(row.badge)
    else row.badge.remove()
    const texts = [
      g.completion_pct.toFixed(0),
      fmtPlaytime(g.playtime_minutes),
      fmtHoursPrecise(r.rush),
      fmtHoursPrecise(r.leisure),
      fmtHoursPrecise(r.worst),
      String(g.count_comp),
      tierLabel(g.protondb_tier, g.protondb_trending_tier),
    ]
    texts.forEach((text, i) => { row.cells[i].textContent = text })
    row.keep.checked = !r.excluded
    row.keep.setAttribute('aria-label', r.excluded ? 'Re-include' : 'Exclude')
    return row.tr
  }

  private syncOptions(all: readonly GameRow[], table: TableState): void {
    for (const [c, select] of this.selects) {
      const current = table.filters.get(c.key) ?? ''
      const want = ['', ...optionsFor(c, all, current)]
      const have = [...select.options].map((o) => o.value)
      if (want.join('\n') !== have.join('\n')) {
        select.replaceChildren(...want.map((v) => h('option', { value: v }, v ? optionLabel(c, v) : 'All')))
      }
      select.value = current
    }
  }

  private syncHeads(table: TableState): void {
    for (const [c, th, button] of this.heads) {
      const active = c.key === table.sort
      const arrow = active ? (table.asc ? ' ▲' : ' ▼') : ''
      button.textContent = `${c.label}${arrow}`
      if (active) th.setAttribute('aria-sort', table.asc ? 'ascending' : 'descending')
      else th.removeAttribute('aria-sort')
    }
  }
}
