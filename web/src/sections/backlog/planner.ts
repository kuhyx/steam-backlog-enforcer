// The backlog-completion planner (was PlannerView). One object owns the
// estimate filters and the table's sort/filter/search state, because the
// summary cards, the timeline and the table all render from the same
// filtered estimate.
//
// Every control is built once: a refresh rewrites text, classes and row
// order only, so a filter box keeps its focus and caret while typing. State
// lives in the URL hash (see tableState.ts / plannerFilters.ts) and is
// restored on load and on a hand-edited hash.

import { applyFilters } from '../../estimate'
import { timelineChart } from '../../lib/charts/timeline'
import { h } from '../../lib/dom'
import { buildIndex, type Searchable } from '../../library/fuzzy'
import type { Filters, WebDataset } from '../../types'
import { glyph } from '../../ui/build'
import { FilterPanel } from './filterPanel'
import { defaultFilters, readFilters, writeFilters } from './plannerFilters'
import { PlannerTable } from './plannerTable'
import { summaryCards } from './summary'
import { readTable, toggleSort, visibleRows, writeTable, type TableState } from './tableState'

/** The live parts of a built planner. */
export class Planner {
  readonly nodes: HTMLElement[]
  private data: WebDataset
  private index: Map<number, Searchable>
  private defaults: Filters
  private filters: Filters
  private table: TableState
  private readonly panel: FilterPanel
  private readonly sub = h('p', { class: 'sub' })
  private summary: HTMLElement = h('div')
  private chart: HTMLElement = h('div')
  private readonly view = new PlannerTable({
    onSort: (key) => {
      this.table = toggleSort(this.table, key)
      this.refresh()
    },
    onColumnFilter: (id, value) => {
      if (value) this.table.filters.set(id, value)
      else this.table.filters.delete(id)
      this.refresh()
    },
    onSearch: (value) => {
      this.filters = { ...this.filters, search: value }
      this.refresh()
    },
    onToggle: (appId) => {
      this.toggleExclude(appId)
    },
  })

  constructor(data: WebDataset) {
    this.data = data
    this.index = buildIndex(data.games)
    this.defaults = defaultFilters(data.defaults)
    this.filters = this.defaults
    this.table = readTable(new URLSearchParams())
    this.panel = new FilterPanel(data.defaults, (patch) => { this.patch(patch) }, () => { this.reset() })
    const content = h('div', { class: 'content' }, this.summary, this.chart, this.view.el)
    this.nodes = [
      // Textgate: the heading is spoken only; the page's rail icon names it.
      h('header', { class: 'app-head' }, h('div', {}, h('h1', { class: 'sr-only' }, 'Backlog Completion Planner'), this.sub)),
      h('div', { class: 'layout' }, this.panel.el, content),
    ]
    this.restore()
  }

  /** A newer dataset: keep every filter, re-derive everything else. */
  setData(data: WebDataset): void {
    this.data = data
    this.index = buildIndex(data.games)
    this.refresh()
  }

  /** Adopt the state in `location.hash` and show it in every control. */
  restore(): void {
    const p = new URLSearchParams(location.hash.slice(1))
    this.table = readTable(p)
    this.filters = readFilters(p, this.defaults)
    this.syncControls()
    this.refresh()
  }

  private patch(patch: Partial<Filters>): void {
    this.filters = { ...this.filters, ...patch }
    this.panel.sync(this.filters)
    this.refresh()
  }

  private reset(): void {
    this.filters = { ...this.defaults, excluded: new Set<number>() }
    this.table = { ...this.table, filters: new Map() }
    this.syncControls()
    this.refresh()
  }

  private toggleExclude(appId: number): void {
    const next = new Set(this.filters.excluded)
    if (next.has(appId)) next.delete(appId)
    else next.add(appId)
    this.filters = { ...this.filters, excluded: next }
    this.refresh()
  }

  private syncControls(): void {
    this.panel.sync(this.filters)
    this.view.syncInputs(this.filters.search, this.table.filters)
  }

  private syncSub(): void {
    const s = this.data.state
    this.sub.replaceChildren(
      ...(s.current_game_name ? [glyph('▶️', 'Currently playing '), ' ', h('strong', {}, s.current_game_name), ' · '] : []),
      glyph('🏆', 'games finished'),
      ` ${s.games_done_since_start} · `,
      glyph('📅', 'since'),
      ` ${s.enforcement_started_at.slice(0, 10) || '—'} · `,
      glyph('🎮', 'candidates'),
      ` ${this.data.games.length}`,
    )
  }

  private writeHash(): void {
    const p = new URLSearchParams()
    writeTable(this.table, p)
    writeFilters(this.filters, this.defaults, p)
    const next = p.toString()
    if (location.hash.slice(1) === next) return
    history.replaceState(history.state, '', next ? `#${next}` : location.pathname + location.search)
  }

  private refresh(): void {
    const { data, filters } = this
    const result = applyFilters(data, filters)
    this.syncSub()
    const summary = summaryCards({
      result,
      filters,
      state: data.state,
      presets: data.defaults.hours_per_day_presets,
      defaultQualifying: data.default_summary.qualifying,
      paceVsHltb: data.pace_vs_hltb,
    })
    this.summary.replaceWith(summary)
    this.summary = summary
    const chart = timelineChart(result, filters, data.state)
    this.chart.replaceWith(chart)
    this.chart = chart

    const visible = visibleRows(
      result.rows.filter((r) => r.passesFilters),
      this.table,
      filters.search,
      this.index,
    )
    this.view.show(result.rows, visible, this.table)
    this.writeHash()
  }
}
