// The planner's estimate filters (was FilterPanel.tsx). Built once; `sync()`
// writes values, active segments and conditional rows in place, so a slider
// being dragged or a date being typed never loses focus.
// Textgate: every label is a glyph (glyphs.ts) with its words spoken only;
// slider values (numbers + units) stay painted.

import { h } from '../../lib/dom'
import { SELECTABLE_TIERS } from '../../protondb'
import type { EstimateBasis, Filters, PlaytimeMode, ProtonMode, WebDefaults } from '../../types'
import { glyph } from '../../ui/build'
import { ANY_GLYPH, BASIS_GLYPH, TIER_GLYPH } from './glyphs'

type Update = (patch: Partial<Filters>) => void
interface Seg<T> { id: T; label: string; icon: string }

const BASES: readonly Seg<EstimateBasis>[] = [
  { id: 'rush', label: 'Rush', icon: BASIS_GLYPH.rush },
  { id: 'leisure', label: 'Leisure', icon: BASIS_GLYPH.leisure },
  { id: 'worst', label: 'Worst', icon: BASIS_GLYPH.worst },
  { id: 'pace', label: 'Pace', icon: BASIS_GLYPH.pace },
]
const PROTON: readonly Seg<ProtonMode>[] = [
  { id: 'playable', label: 'Playable (CLI rule)', icon: '⌨️' },
  { id: 'minTier', label: 'Min tier', icon: '🥇≥' },
]
const PLAYTIME: readonly Seg<PlaytimeMode>[] = [
  { id: 'all', label: 'All', icon: ANY_GLYPH },
  { id: 'started', label: 'Started', icon: '▶️' },
  { id: 'untouched', label: 'Untouched', icon: '∅' },
]

type NumberKey = 'dailyHours' | 'minCountComp' | 'minComp100' | 'minConfidenceSum' | 'maxHoursPerGame' | 'fallbackHours'

interface Slider {
  key: NumberKey
  input: HTMLInputElement
  val: HTMLSpanElement
  show: (f: Filters) => string
}

const hint = (text: string) => h('p', { class: 'hint sr-only' }, text)

export class FilterPanel {
  readonly el: HTMLElement
  private readonly syncs: ((f: Filters) => void)[] = []

  constructor(defaults: WebDefaults, update: Update, onReset: () => void) {
    const slider = (key: NumberKey, icon: string, label: string, min: number, max: number, step: number, show: Slider['show']) => {
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
      return { label: h('label', {}, glyph(icon, label), ' ', val), input }
    }
    const segmented = <T extends string>(items: readonly Seg<T>[], current: (f: Filters) => T, set: (id: T) => void) => {
      const buttons = items.map((it) =>
        h('button', { type: 'button', class: 'seg', 'aria-label': it.label, onclick: () => { set(it.id) } }, it.icon),
      )
      this.syncs.push((f) => {
        buttons.forEach((b, i) => {
          const on = items[i]?.id === current(f)
          b.classList.toggle('active', on)
          b.setAttribute('aria-pressed', String(on))
        })
      })
      return h('div', { class: 'segmented' }, buttons)
    }
    const check = (icon: string, label: string, read: (f: Filters) => boolean, set: (on: boolean) => void) => {
      const input = h('input', { type: 'checkbox' })
      input.addEventListener('change', () => {
        set(input.checked)
      })
      this.syncs.push((f) => {
        input.checked = read(f)
      })
      return h('label', { class: 'check' }, input, glyph(icon, label))
    }
    const shownWhen = <E extends HTMLElement>(el: E, when: (f: Filters) => boolean): E => {
      this.syncs.push((f) => {
        el.hidden = !when(f)
      })
      return el
    }
    const heading = (icon: string, label: string) => h('label', {}, glyph(icon, label))

    const daily = slider('dailyHours', '⏰', 'Daily play time', 0.5, 16, 0.5, (f) => `${f.dailyHours} h/day`)
    const minComp = slider('minCountComp', '#', 'Min HLTB completions', 0, 100, 1, (f) => String(f.minCountComp))
    const min100 = slider('minComp100', '💯', 'Min polled completionist times', 0, 50, 1, (f) => String(f.minComp100))
    const minConf = slider('minConfidenceSum', 'Σ', 'Min confidence sum', 0, 150, 1, (f) => String(f.minConfidenceSum))
    const maxH = slider('maxHoursPerGame', '⏳', 'Max time per game', 0, 200, 5, (f) =>
      f.maxHoursPerGame > 0 ? `${f.maxHoursPerGame} h` : '∞',
    )
    const fallback = slider('fallbackHours', '❓', 'Fallback estimate', 1, 100, 1, (f) => `${f.fallbackHours} h`)

    const tier = h(
      'select',
      { 'aria-label': 'Minimum ProtonDB tier' },
      SELECTABLE_TIERS.map((t) => h('option', { value: t, 'aria-label': t }, TIER_GLYPH[t])),
    )
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
      h('button', { type: 'button', class: 'ghost', 'aria-label': 'Clear', onclick: () => { update({ targetDate: '' }) } }, '✕'),
      (f) => f.targetDate !== '',
    )

    this.el = h(
      'aside',
      { class: 'panel' },
      h(
        'div',
        { class: 'panel-head' },
        h('h2', {}, glyph('🎚️', 'Filters')),
        h('button', { type: 'button', class: 'ghost', 'aria-label': 'Reset to CLI defaults', onclick: () => { onReset() } }, '↺ ⌨️'),
      ),
      h('section', { class: 'field' }, heading('📐', 'Estimate basis'), segmented(BASES, (f) => f.basis, (basis) => { update({ basis }) })),
      h('section', { class: 'field' }, daily.label, daily.input),
      h(
        'section',
        { class: 'field' },
        minComp.label,
        minComp.input,
        hint(`Higher = more reliable HLTB times (CLI default ${defaults.min_count_comp}).`),
      ),
      h('details', { class: 'field' }, h('summary', {}, glyph('🔬', 'Advanced confidence')), min100.label, min100.input, minConf.label, minConf.input),
      h(
        'section',
        { class: 'field' },
        heading('🐧', 'ProtonDB compatibility'),
        segmented(PROTON, (f) => f.protonMode, (protonMode) => { update({ protonMode }) }),
        shownWhen(
          h(
            'div',
            { class: 'subfield' },
            tier,
            check('❓', 'Keep games with no ProtonDB data', (f) => f.protonTreatMissingAsPass, (on) => {
              update({ protonTreatMissingAsPass: on })
            }),
          ),
          (f) => f.protonMode === 'minTier',
        ),
      ),
      h('section', { class: 'field' }, maxH.label, maxH.input, hint('Hide games longer than this (0 = no cap).')),
      h(
        'section',
        { class: 'field' },
        heading('⏱', 'Playtime'),
        segmented(PLAYTIME, (f) => f.playtimeMode, (playtimeMode) => { update({ playtimeMode }) }),
      ),
      h(
        'section',
        { class: 'field' },
        check('❓', 'Include games with no HLTB data', (f) => f.includeNoData, (on) => {
          update({ includeNoData: on })
        }),
        shownWhen(h('div', { class: 'subfield' }, fallback.label, fallback.input), (f) => f.includeNoData),
      ),
      h(
        'section',
        { class: 'field' },
        heading('🏁', 'Target finish date'),
        h('div', { class: 'subfield row' }, date, clear),
        hint('Pick a date to see the hours/day required.'),
      ),
    )
  }

  /** Show `f` without replacing any control. */
  sync(f: Filters): void {
    for (const fn of this.syncs) fn(f)
  }
}
