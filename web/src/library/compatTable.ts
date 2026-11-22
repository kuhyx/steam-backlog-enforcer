// <compat-table>: the Proton map, every installed game's compat-tool decision
// (`GET /api/compat`, the installer's own map-installed rows) with the R3
// table defaults: a sortable header and a filter on every column, fuzzy
// search, state in the URL hash (`c.` keys, compatState.ts) and a 30 s poll.
// Built once; a refresh repaints rows in place, so typing never loses focus.
// The apply button runs `map-installed` on the selected rows, or on every
// visible row that would change; the server checks the phrase and the
// game-running guard. Textgate: headers and marks are icons with spoken
// names and one-word hovers; only data (names, ids, tools, reasons) is text.

import type { CompatRow } from '../api/contract'
import { q } from '../api/queries'
import type { IconId } from '../icons/registry'
import { iconText } from '../icons/iconText'
import { iconInline } from '../icons/render'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { runner } from '../lib/runner'
import { errorNotice, loading } from '../ui/build'
import {
  COMPAT_COLUMNS,
  compatOptions,
  readCompat,
  toggleCompatSort,
  visibleCompat,
  whyText,
  writeCompat,
  type CompatColumn,
  type CompatKey,
  type CompatState,
} from './compatState'
import { buildIndex, type Searchable } from './fuzzy'
import { readHash, replaceHash } from './hashState'

const COLUMN_ICON = {
  name: 'libpage.game',
  app_id: 'libpage.app-id',
  current: 'compat.current',
  decided: 'compat.decided',
  why: 'compat.why',
  changes: 'compat.changes',
} as const satisfies Record<CompatKey, IconId>

/** A painted icon that is the cell's whole content: spoken as an image. */
const mark = (id: IconId, spoken: string) => h('span', { role: 'img', 'aria-label': spoken }, iconInline(id))
const toolCell = (tool: string | null) => tool ?? mark('compat.valve', 'Valve default')
// An <option> holds text only: the changes column's options are its marks' glyphs.
const optionLabel = (c: CompatColumn, v: string) =>
  c.key === 'changes' ? iconText(v === 'changes' ? 'compat.changes' : 'compat.same') : v

interface RowEls {
  tr: HTMLTableRowElement
  select: HTMLInputElement
  /** The select cell, then one per column. */
  cells: HTMLTableCellElement[]
}

export class CompatTableElement extends LiveElement {
  private state: CompatState = readCompat(readHash())
  private rows: CompatRow[] = []
  private index = new Map<number, Searchable>()
  private readonly selected = new Set<number>()
  private readonly els = new Map<number, RowEls>()
  private readonly heads: [CompatColumn, HTMLTableCellElement][] = []
  private readonly inputs = new Map<string, HTMLInputElement | HTMLSelectElement>()
  private readonly tbody = h('tbody')
  private readonly count = h('span', { class: 'games-count' })
  private readonly search = h('input', { type: 'search', 'aria-label': 'Search games', placeholder: '' })
  private readonly apply = h('button', { type: 'button', class: 'btn btn-danger' })
  private readonly view = h('div', { class: 'table-wrap' })

  protected override setup(): void {
    this.watch(q.compat)
    this.search.addEventListener('input', () => {
      this.set({ ...this.state, query: this.search.value })
    })
    this.apply.addEventListener('click', () => {
      // Disabled at 0 targets, so a click always has ids to send.
      runner.run('map-installed', { appids: this.targets().join(',') })
    })
    this.buildTable()
    const onHash = () => {
      this.state = readCompat(readHash())
      this.paint()
    }
    window.addEventListener('hashchange', onHash)
    this.onCleanup(() => {
      window.removeEventListener('hashchange', onHash)
    })
  }

  protected update(): void {
    const { data, error } = q.compat.state
    if (!data) {
      this.replaceChildren(h('div', { class: 'status' }, error ? errorNotice(error) : loading('Proton map')))
      return
    }
    this.rows = data.rows
    this.index = buildIndex(data.rows)
    // A refresh can turn a selected game into one that no longer changes.
    const changing = new Set(data.rows.filter((r) => r.changes).map((r) => r.app_id))
    for (const id of [...this.selected]) if (!changing.has(id)) this.selected.delete(id)
    if (this.firstElementChild !== this.view) this.replaceChildren(this.view)
    this.paint()
  }

  private set(next: CompatState): void {
    this.state = next
    const p = readHash()
    writeCompat(next, p)
    replaceHash(p)
    this.paint()
  }

  /** The selected games, or every visible one that would change. */
  private targets(): number[] {
    if (this.selected.size > 0) return this.rows.filter((r) => this.selected.has(r.app_id)).map((r) => r.app_id)
    return visibleCompat(this.rows, this.state, this.index).filter((r) => r.changes).map((r) => r.app_id)
  }

  private buildTable(): void {
    const headCell = (c: CompatColumn) => {
      const th = h('th', { class: c.numeric ? 'num clickable' : 'clickable', scope: 'col', 'aria-label': c.label })
      th.addEventListener('click', () => {
        this.set(toggleCompatSort(this.state, c.key))
      })
      this.heads.push([c, th])
      return th
    }
    const field = (id: string, el: HTMLInputElement | HTMLSelectElement) => {
      this.inputs.set(id, el)
      el.addEventListener(el instanceof HTMLSelectElement ? 'change' : 'input', () => {
        const filters = new Map(this.state.filters)
        if (el.value) filters.set(id, el.value)
        else filters.delete(id)
        this.set({ ...this.state, filters })
      })
      return el
    }
    const filterCell = (c: CompatColumn) => {
      if (c.filter === 'range') {
        const side = (s: 'min' | 'max') =>
          field(`${c.key}.${s}`, h('input', { type: 'number', inputmode: 'numeric', placeholder: s === 'min' ? '≥' : '≤', 'aria-label': `${c.label} ${s}` }))
        return h('td', { class: 'range-filter' }, h('div', {}, side('min'), side('max')))
      }
      if (c.filter === 'select') return h('td', {}, field(c.key, h('select', { 'aria-label': `Filter ${c.label}` })))
      return h('td', {}, field(c.key, h('input', { type: 'search', placeholder: '', 'aria-label': `Filter ${c.label}` })))
    }
    this.view.replaceChildren(
      h('div', { class: 'table-head' }, this.count, this.search, this.apply),
      h(
        'div',
        { class: 'table-scroll', role: 'region', 'aria-label': 'Proton map', tabindex: 0 },
        h(
          'table',
          {},
          h(
            'thead',
            {},
            h('tr', {}, h('th', { scope: 'col', 'aria-label': 'Select' }, iconInline('compat.select')), COMPAT_COLUMNS.map(headCell)),
            h('tr', { class: 'filter-row' }, h('td'), COMPAT_COLUMNS.map(filterCell)),
          ),
          this.tbody,
        ),
      ),
    )
  }

  private rowFor(r: CompatRow): HTMLTableRowElement {
    let els = this.els.get(r.app_id)
    if (!els) {
      const select = h('input', { type: 'checkbox', 'aria-label': `Select ${r.name}` })
      select.addEventListener('change', () => {
        if (select.checked) this.selected.add(r.app_id)
        else this.selected.delete(r.app_id)
        this.paintApply()
      })
      const classes = ['', 'name', 'num mono muted', '', '', 'why', 'num']
      const cells = classes.map((c) => h('td', c ? { class: c } : {}))
      els = { tr: h('tr', {}, cells), select, cells }
      this.els.set(r.app_id, els)
    }
    const [pick, ...cells] = els.cells
    // The checkbox stays put across repaints (focus); only changing rows get one.
    if ((els.select.parentNode === pick) !== r.changes) pick.replaceChildren(...(r.changes ? [els.select] : []))
    els.select.checked = this.selected.has(r.app_id)
    els.tr.className = r.changes ? 'changes' : ''
    const content = [
      r.name,
      String(r.app_id),
      toolCell(r.current),
      toolCell(r.decided),
      whyText(r) || mark('compat.safe', 'Safe to map'),
      r.changes ? mark('compat.changes', 'Changes') : mark('compat.same', 'Unchanged'),
    ]
    content.forEach((child, i) => {
      cells[i].replaceChildren(child)
    })
    return els.tr
  }

  private paint(): void {
    const s = this.state
    for (const [c, th] of this.heads) {
      const active = c.key === s.sort
      th.replaceChildren(iconInline(COLUMN_ICON[c.key]), ...(active ? [' ', iconInline(s.asc ? 'backlog.sort-asc' : 'backlog.sort-desc')] : []))
      if (active) th.setAttribute('aria-sort', s.asc ? 'ascending' : 'descending')
      else th.removeAttribute('aria-sort')
    }
    for (const [id, input] of this.inputs) {
      const c = COMPAT_COLUMNS.find((col) => col.key === id)
      const value = s.filters.get(id) ?? ''
      if (c && input instanceof HTMLSelectElement) {
        const opts = ['', ...compatOptions(c, this.rows, value)]
        if ([...input.options].map((o) => o.value).join('\n') !== opts.join('\n')) {
          input.replaceChildren(...opts.map((v) => h('option', { value: v, 'aria-label': v || 'All' }, v ? optionLabel(c, v) : iconText('backlog.any'))))
        }
      }
      if (input.value !== value) input.value = value
    }
    if (this.search.value !== s.query) this.search.value = s.query
    const visible = visibleCompat(this.rows, s, this.index)
    const trs = visible.map((r) => this.rowFor(r))
    const current = this.tbody.children
    if (trs.length !== current.length || trs.some((tr, i) => current[i] !== tr)) this.tbody.replaceChildren(...trs)
    this.count.textContent = `${visible.length}/${this.rows.length}`
    this.count.setAttribute('aria-label', `${visible.length} of ${this.rows.length} games`)
    this.paintApply()
  }

  private paintApply(): void {
    const n = this.targets().length
    this.apply.disabled = n === 0
    this.apply.setAttribute('aria-label', `Map ${n} games`)
    this.apply.replaceChildren(iconInline('cmd.map-installed'), ` ${n}`)
  }
}

define('compat-table', CompatTableElement)
