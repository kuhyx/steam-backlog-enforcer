// The widgets of the icon-word picker (picker.ts holds the state and keys).
// A developer page the user asked to carry text: the description, the
// suggestions and the key hints are meant to be read.

import { progressBar } from '../jobs/progress'
import { h, type Child } from '../lib/dom'
import { errorNotice } from '../ui/build'
import { choiceOf } from './ledger'
import { contextPreview } from './preview'
import type { IconEntry } from './registry'
import { iconFor } from './render'
import { sentenceCase } from './textCase'

export interface PickerHandlers {
  word: (slot: number) => void
  own: (text: string) => void
  skip: () => void
  /** null keeps the default glyph. */
  glyph: (slot: number | null) => void
  go: (to: number) => void
  jump: () => void
  showWords: (on: boolean) => void
}

export interface PickerState {
  index: number
  total: number
  answered: number
  entry: IconEntry | null
  error: unknown
  invalid: boolean
  /** The own-word text to keep in the field (a refused entry). */
  draft: string | null
  wordsShown: boolean
}

const keyed = (key: string, ...label: Child[]) => [h('kbd', {}, key), ...label]

function choiceButton(attrs: Record<string, string>, pressed: boolean, onclick: () => void, ...label: Child[]) {
  return h('button', { type: 'button', class: 'btn btn-ghost picker-choice', 'aria-pressed': String(pressed), onclick, ...attrs }, ...label)
}

function ownForm(s: PickerState, entry: IconEntry, on: PickerHandlers, saved: string | null | undefined): HTMLFormElement {
  const own = typeof saved === 'string' && !entry.words.includes(saved) ? saved : ''
  const input = h('input', { class: 'input', name: 'own', autocomplete: 'off', 'aria-invalid': String(s.invalid), value: s.draft ?? own })
  const form = h(
    'form',
    { class: 'picker-own' },
    h('label', { class: 'picker-own-label' }, h('span', {}, ...keyed('O', ' Own word')), input),
    h('button', { type: 'submit', class: 'btn btn-primary' }, '✓ ', h('kbd', {}, '⏎')),
  )
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    on.own(input.value)
  })
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') input.blur()
  })
  return form
}

function choices(s: PickerState, entry: IconEntry, on: PickerHandlers): HTMLElement {
  const saved = choiceOf(entry.id)
  const glyph = saved.glyph && entry.alts.includes(saved.glyph) ? saved.glyph : null
  return h(
    'div',
    { class: 'picker-choices stack' },
    h('p', { class: 'picker-desc m0' }, entry.desc),
    h(
      'div',
      { class: 'picker-words' },
      entry.words.map((w, i) => choiceButton({ 'data-word-slot': String(i) }, saved.word === w, () => { on.word(i) }, ...keyed(String(i + 1), w))),
    ),
    ownForm(s, entry, on, saved.word),
    choiceButton({ 'data-skip': '' }, saved.word === null, on.skip, ...keyed('S', ' Skip (no word)')),
    h(
      'div',
      { class: 'picker-glyphs', role: 'group', 'aria-label': 'Glyph' },
      choiceButton({ 'data-glyph-slot': 'default' }, glyph === null, () => { on.glyph(null) }, ...keyed('6', ` ${entry.glyph} keep default`)),
      entry.alts.map((a, i) => choiceButton({ 'data-glyph-slot': String(i) }, glyph === a, () => { on.glyph(i) }, ...keyed(String(i + 7), ` ${a}`))),
    ),
  )
}

function header(s: PickerState, entry: IconEntry): HTMLElement {
  const word = choiceOf(entry.id).word
  const saved = typeof word === 'string' ? sentenceCase(word) : word === null ? '— skipped' : ''
  return h(
    'div',
    { class: 'picker-head' },
    h('span', { class: 'picker-count' }, `${String(s.index + 1)} / ${String(s.total)}`),
    h('code', { class: 'picker-id' }, entry.id),
    h('span', { class: 'picker-saved' }, saved),
  )
}

function footer(s: PickerState, on: PickerHandlers): HTMLElement {
  return h(
    'div',
    { class: 'picker-nav' },
    h('button', { type: 'button', class: 'btn btn-ghost', 'data-go': '-1', disabled: s.index === 0, onclick: () => { on.go(s.index - 1) } }, '← back'),
    h('label', { class: 'picker-toggle' }, h('input', { type: 'checkbox', name: 'show-words', checked: s.wordsShown, onchange: (e: Event) => { on.showWords((e.target as HTMLInputElement).checked) } }), ' Show words next to icons'),
    h('button', { type: 'button', class: 'btn btn-ghost', 'data-go': '1', disabled: s.entry === null, onclick: () => { on.go(s.index + 1) } }, 'forward →'),
  )
}

function done(s: PickerState, on: PickerHandlers): HTMLElement {
  return h(
    'div',
    { class: 'picker-done stack' },
    h('p', { class: 'picker-summary m0' }, `${String(s.answered)} / ${String(s.total)}`),
    s.answered < s.total ? h('button', { type: 'button', class: 'btn btn-primary', 'data-jump': '', onclick: on.jump }, 'Next unanswered') : h('p', { class: 'm0' }, '✅'),
  )
}

/** The error slot (also all there is when the ledger could not be read). */
export function pickerStatus(error: unknown): HTMLElement {
  return h('div', { class: 'picker-status' }, error ? errorNotice(error) : null)
}

/** Everything the loaded picker shows for `s`. */
export function pickerView(s: PickerState, on: PickerHandlers): HTMLElement[] {
  const status = pickerStatus(s.error)
  const bar = progressBar(s.answered / s.total, 'Answered')
  if (!s.entry) return [bar, status, done(s, on), footer(s, on)]
  const stage = h('div', { class: 'picker-stage' }, h('div', { class: 'picker-big', 'aria-hidden': 'true' }, iconFor(s.entry.id).glyph), contextPreview(s.entry.id))
  return [header(s, s.entry), bar, status, h('div', { class: 'picker-body' }, stage, choices(s, s.entry, on)), footer(s, on)]
}
