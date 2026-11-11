// The runner's parameter fields (was ParamsForm.tsx). Inputs are built once
// per spec list; `refresh()` only updates validity and help text, so typing
// never re-creates an input.

import type { ParamSpec } from '../api/contract'
import { h } from '../lib/dom'
import { uid } from '../lib/ids'
import { paramError, type GameOption, type ParamValues } from './params'

/** Painted glyph per parameter (textgate); the catalog label is spoken only. */
const PARAM_ICON: Record<string, string> = {
  app_id: '🎮',
  backup_id: '🗄️',
  days: '📅',
  minutes: '⏱️',
  reason: '💬',
  replace: '🔁',
  demo: '🧪',
}

function paramGlyph(spec: ParamSpec): HTMLSpanElement {
  return h(
    'span',
    {},
    h('span', { 'aria-hidden': 'true' }, PARAM_ICON[spec.name] ?? '✏️'),
    h('span', { class: 'sr-only' }, spec.label),
  )
}

/** Field help: optional painted mark, sentence spoken only. */
function spokenHelp(el: HTMLElement, mark: string | null, sentence: string): void {
  el.replaceChildren(
    mark ? h('span', { 'aria-hidden': 'true' }, mark) : '',
    sentence ? h('span', { class: 'sr-only' }, sentence) : '',
  )
}

interface Field {
  wrap: HTMLDivElement
  spec: ParamSpec
  input: HTMLInputElement
  help: HTMLParagraphElement
  datalist: HTMLDataListElement | null
}

export interface ParamsFormOptions {
  specs: ParamSpec[]
  values: ParamValues
  disabled: boolean
  onChange: (values: ParamValues) => void
}

export class ParamsForm {
  readonly nodes: HTMLDivElement[]
  private readonly fields: Field[]
  private values: ParamValues
  private games: GameOption[] = []
  private showErrors = false

  constructor({ specs, values, disabled, onChange }: ParamsFormOptions) {
    this.values = { ...values }
    const base = uid('param')
    this.fields = specs.map((spec, i) => this.field(spec, `${base}-${spec.name}`, i === 0, disabled, onChange))
    this.nodes = this.fields.map((f) => f.wrap)
    this.refresh()
  }

  /** New game list (app_id pickers) and/or error visibility. */
  refresh(games: GameOption[] = this.games, showErrors: boolean = this.showErrors): void {
    this.games = games
    this.showErrors = showErrors
    for (const f of this.fields) this.refreshField(f)
  }

  private field(
    spec: ParamSpec,
    id: string,
    first: boolean,
    disabled: boolean,
    onChange: (values: ParamValues) => void,
  ): Field {
    const raw = this.values[spec.name] ?? ''
    const help = h('p', { id: `${id}-help`, class: 'field-help' })
    const emit = (value: string) => {
      this.values = { ...this.values, [spec.name]: value }
      this.refresh()
      onChange(this.values)
    }
    if (spec.type === 'bool') {
      const input = h('input', { id, type: 'checkbox', disabled, 'aria-describedby': `${id}-help` })
      input.checked = raw === '1'
      input.addEventListener('change', () => {
        emit(input.checked ? '1' : '0')
      })
      const wrap = h('div', { class: 'form-field' }, h('label', { class: 'check', for: id }, input, paramGlyph(spec)), help)
      return { wrap, spec, input, help, datalist: null }
    }
    const numeric = spec.type !== 'string'
    const datalist = spec.type === 'app_id' ? h('datalist', { id: `${id}-games` }) : null
    const input = h('input', {
      id,
      class: numeric ? 'input input-num' : 'input',
      type: spec.type === 'int' ? 'number' : 'text',
      inputmode: numeric ? 'numeric' : null,
      min: spec.min,
      max: spec.max,
      list: datalist ? `${id}-games` : null,
      required: spec.required,
      disabled,
      autofocus: first,
      'aria-describedby': `${id}-help`,
    })
    input.value = raw
    input.addEventListener('input', () => {
      emit(input.value)
    })
    const wrap = h(
      'div',
      { class: 'form-field' },
      h('label', { for: id, class: 'field-label' }, paramGlyph(spec), spec.required ? h('span', { 'aria-hidden': 'true' }, ' *') : null),
      input,
      datalist,
      help,
    )
    return { wrap, spec, input, help, datalist }
  }

  private refreshField({ spec, input, help, datalist }: Field): void {
    if (spec.type === 'bool') {
      spokenHelp(help, null, spec.help ?? '')
      return
    }
    const raw = this.values[spec.name] ?? ''
    const err = paramError(spec, raw, this.games)
    const bad = this.showErrors && err !== null
    input.classList.toggle('input-bad', bad)
    input.setAttribute('aria-invalid', String(bad))
    help.className = bad ? 'field-help text-danger' : 'field-help'
    const game = spec.type === 'app_id' ? this.games.find((g) => g.app_id === Number(raw)) : undefined
    // Textgate: an error paints ⚠️, a matched game paints its name (content);
    // the error sentence and the field help are spoken only.
    if (bad) spokenHelp(help, '⚠️', err)
    else if (game) help.replaceChildren(game.name)
    else spokenHelp(help, null, spec.help ?? (spec.type === 'app_id' ? 'Type an app id or pick a game from the list.' : ''))
    if (datalist && datalist.childElementCount !== this.games.length) {
      datalist.replaceChildren(...this.games.map((g) => h('option', { value: g.app_id }, g.name)))
    }
  }
}
