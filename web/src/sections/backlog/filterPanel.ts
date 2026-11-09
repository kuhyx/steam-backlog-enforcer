// The planner's estimate filters (was FilterPanel.tsx). Built once; `sync()`
// writes values, active segments and conditional rows in place, so a slider
// being dragged or a date being typed never loses focus.

import { h } from '../../lib/dom'
import { SELECTABLE_TIERS } from '../../protondb'
import type { EstimateBasis, Filters, PlaytimeMode, ProtonMode, WebDefaults } from '../../types'

type Update = (patch: Partial<Filters>) => void

const BASES: readonly { id: EstimateBasis; label: string }[] = [
  { id: 'rush', label: 'Rush' },
  { id: 'leisure', label: 'Leisure' },
  { id: 'worst', label: 'Worst' },
  { id: 'pace', label: 'Pace' },
]
const PROTON: readonly { id: ProtonMode; label: string }[] = [
  { id: 'playable', label: 'Playable (CLI rule)' },
  { id: 'minTier', label: 'Min tier' },
]
const PLAYTIME: readonly { id: PlaytimeMode; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'started', label: 'Started' },
  { id: 'untouched', label: 'Untouched' },
]

type NumberKey = 'dailyHours' | 'minCountComp' | 'minComp100' | 'minConfidenceSum' | 'maxHoursPerGame' | 'fallbackHours'

interface Slider {
  key: NumberKey
  input: HTMLInputElement
  val: HTMLSpanElement
  show: (f: Filters) => string
}

export class FilterPanel {
  readonly el: HTMLElement
  private readonly syncs: ((f: Filters) => void)[] = []

  constructor(defaults: WebDefaults, update: Update, onReset: () => void) {
    const slider = (key: NumberKey, label: string, min: number, max: number, step: number, show: Slider['show']) => {
      const val = h('span', { class: 'val' })
      const input = h('input', { type: 'range', min, max, step, 'aria-label': label })
      input.addEventListener('input', () => {
        const patch: Partial<Filters> = {}
        patch[key] = Number(input.value)
        update(patch)
      })
      this.syncs.push((f) => {
        input.value = String(f[key])
        val.textContent = show(f)
      })
      return { label: h('label', {}, `${label} `, val), input }
    }
    const segmented = <T extends string>(items: readonly { id: T; label: string }[], current: (f: Filters) => T, set: (id: T) => void) => {
      const buttons = items.map((it) =>
        h('button', { type: 'button', class: 'seg', onclick: () => { set(it.id) } }, it.label),
      )
      this.syncs.push((f) => {
        buttons.forEach((b, i) => b.classList.toggle('active', items[i]?.id === current(f)))
      })
      return h('div', { class: 'segmented' }, buttons)
    }
    const check = (label: string, read: (f: Filters) => boolean, set: (on: boolean) => void) => {
      const input = h('input', { type: 'checkbox' })
      input.addEventListener('change', () => {
        set(input.checked)
      })
      this.syncs.push((f) => {
        input.checked = read(f)
      })
      return h('label', { class: 'check' }, input, label)
    }
    const shownWhen = <E extends HTMLElement>(el: E, when: (f: Filters) => boolean): E => {
      this.syncs.push((f) => {
        el.hidden = !when(f)
      })
      return el
    }

    const daily = slider('dailyHours', 'Daily play time', 0.5, 16, 0.5, (f) => `${f.dailyHours} h/day`)
    const minComp = slider('minCountComp', 'Min HLTB completions', 0, 100, 1, (f) => String(f.minCountComp))
    const min100 = slider('minComp100', 'Min polled completionist times', 0, 50, 1, (f) => String(f.minComp100))
    const minConf = slider('minConfidenceSum', 'Min confidence sum', 0, 150, 1, (f) => String(f.minConfidenceSum))
    const maxH = slider('maxHoursPerGame', 'Max time per game', 0, 200, 5, (f) =>
      f.maxHoursPerGame > 0 ? `${f.maxHoursPerGame} h` : 'off',
    )
    const fallback = slider('fallbackHours', 'Fallback estimate', 1, 100, 1, (f) => `${f.fallbackHours} h`)

    const tier = h('select', { 'aria-label': 'Minimum ProtonDB tier' }, SELECTABLE_TIERS.map((t) => h('option', { value: t }, t)))
    tier.addEventListener('change', () => {
      update({ protonMinTier: tier.value })
    })
    this.syncs.push((f) => {
      tier.value = f.protonMinTier
    })

    const date = h('input', { type: 'date', 'aria-label': 'Target finish date' })
    date.addEventListener('input', () => {
      update({ targetDate: date.value })
    })
    this.syncs.push((f) => {
      date.value = f.targetDate
    })
    const clear = shownWhen(
      h('button', { type: 'button', class: 'ghost', onclick: () => { update({ targetDate: '' }) } }, 'Clear'),
      (f) => f.targetDate !== '',
    )

    this.el = h(
      'aside',
      { class: 'panel' },
      h(
        'div',
        { class: 'panel-head' },
        h('h2', {}, 'Filters'),
        h('button', { type: 'button', class: 'ghost', onclick: () => { onReset() } }, 'Reset to CLI defaults'),
      ),
      h(
        'section',
        { class: 'field' },
        h('label', {}, 'Estimate basis'),
        segmented(BASES, (f) => f.basis, (basis) => { update({ basis }) }),
      ),
      h('section', { class: 'field' }, daily.label, daily.input),
      h(
        'section',
        { class: 'field' },
        minComp.label,
        minComp.input,
        h('p', { class: 'hint' }, `Higher = more reliable HLTB times (CLI default ${defaults.min_count_comp}).`),
      ),
      h(
        'details',
        { class: 'field' },
        h('summary', {}, 'Advanced confidence'),
        min100.label,
        min100.input,
        minConf.label,
        minConf.input,
      ),
      h(
        'section',
        { class: 'field' },
        h('label', {}, 'ProtonDB compatibility'),
        segmented(PROTON, (f) => f.protonMode, (protonMode) => { update({ protonMode }) }),
        shownWhen(
          h(
            'div',
            { class: 'subfield' },
            tier,
            check('Keep games with no ProtonDB data', (f) => f.protonTreatMissingAsPass, (on) => {
              update({ protonTreatMissingAsPass: on })
            }),
          ),
          (f) => f.protonMode === 'minTier',
        ),
      ),
      h(
        'section',
        { class: 'field' },
        maxH.label,
        maxH.input,
        h('p', { class: 'hint' }, 'Hide games longer than this (0 = no cap).'),
      ),
      h(
        'section',
        { class: 'field' },
        h('label', {}, 'Playtime'),
        segmented(PLAYTIME, (f) => f.playtimeMode, (playtimeMode) => { update({ playtimeMode }) }),
      ),
      h(
        'section',
        { class: 'field' },
        check('Include games with no HLTB data', (f) => f.includeNoData, (on) => {
          update({ includeNoData: on })
        }),
        shownWhen(h('div', { class: 'subfield' }, fallback.label, fallback.input), (f) => f.includeNoData),
      ),
      h(
        'section',
        { class: 'field' },
        h('label', {}, 'Target finish date'),
        h('div', { class: 'subfield row' }, date, clear),
        h('p', { class: 'hint' }, 'Pick a date to see the hours/day required.'),
      ),
    )
  }

  /** Show `f` without replacing any control. */
  sync(f: Filters): void {
    for (const fn of this.syncs) fn(f)
  }
}
