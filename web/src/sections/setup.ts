// Setup page (was screens/Setup.tsx): Steam API key + SteamID64. The key is
// write-only: the server never returns it, so the field always starts empty
// and only says whether one is stored. The form is built once; loads, saves
// and validation only touch notices, classes and help text, never the inputs.
// This page never redirects: the shell's first-run redirect skips /setup/.

import { api } from '../api/client'
import { q } from '../api/queries'
import { Action } from '../lib/action'
import { append, define, h, type Child } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { invalidateAll } from '../lib/query'
import { card, errorNotice, glyph, loading, notice } from '../ui/build'

/** A notice's title and sentence, spoken only (textgate); its tone icon is painted. */
const spoken = (title: string, text: string): HTMLSpanElement =>
  h('span', { class: 'sr-only' }, h('strong', {}, title), ` ${text}`)

const KEY_RE = /^[0-9A-Fa-f]{32}$/
const ID_RE = /^7656\d{13}$/

export function keyError(key: string): string | null {
  return KEY_RE.test(key.trim()) ? null : 'The key is 32 hexadecimal characters.'
}

export function idError(id: string): string | null {
  return ID_RE.test(id.trim()) ? null : 'A SteamID64 is 17 digits and starts with 7656.'
}

// Textgate: help is a 🔗 to where the value comes from; its sentence is spoken only.
const helpLink = (href: string, spoken: string, sentence: string): Child[] => [
  h('a', { href, target: '_blank', rel: 'noreferrer', class: 'setup-link', 'aria-label': spoken }, '🔗'),
  h('span', { class: 'sr-only' }, sentence),
]
const KEY_HELP = (): Child[] =>
  helpLink('https://steamcommunity.com/dev/apikey', 'steamcommunity.com/dev/apikey', 'Get one at steamcommunity.com/dev/apikey. It is never shown again.')
const ID_HELP = (): Child[] => helpLink('https://steamid.io', 'steamid.io', 'Your profile URL or steamid.io shows it.')

/** Placeholders paint the expected shape: one dot per character, the fixed 7656 prefix. */
const KEY_SHAPE = '·'.repeat(32)
const KEY_STORED = `🔒 ${'•'.repeat(32)}`
const ID_SHAPE = `7656${'·'.repeat(13)}`

interface Field {
  input: HTMLInputElement
  help: HTMLParagraphElement
  hint: () => Child[]
  baseClass: string
  /** Characters a valid value has; a bad value paints `⚠️ typed/want`. */
  want: number
}

function field(id: string, label: string, icon: string, input: HTMLInputElement, hint: () => Child[], want: number): { el: HTMLDivElement; f: Field } {
  const help = h('p', { id: `${id}-help`, class: 'field-help' }, hint())
  input.id = id
  input.setAttribute('aria-describedby', `${id}-help`)
  return {
    el: h(
      'div',
      { class: 'form-field' },
      // The glyph is painted beside a spoken-only <label>, so the label's text stays exactly `label`.
      h('span', { class: 'field-label', 'aria-hidden': 'true' }, icon),
      h('label', { for: id, class: 'sr-only' }, label),
      input,
      help,
    ),
    f: { input, help, hint, baseClass: input.className, want },
  }
}

export class SetupFormElement extends LiveElement {
  private readonly status = h('div', { class: 'contents' })
  private readonly saved = h('div', { class: 'contents' })
  private readonly failure = h('div', { class: 'contents' })
  private readonly submit = h('button', { type: 'submit', class: 'btn btn-primary' })
  private readonly keyField: Field
  private readonly idField: Field
  private readonly root: HTMLElement
  private readonly save = new Action(
    () => api.saveSetup({ steam_api_key: this.keyField.input.value.trim(), steam_id: this.idField.input.value.trim() }),
    () => {
      this.render()
    },
  )
  private touched = false
  /** The user edited the id: a later load must not overwrite it. */
  private idEdited = false
  private success = false

  constructor() {
    super()
    const key = field(
      'setup-key',
      'Steam Web API key',
      '🔑',
      h('input', { class: 'input mono', type: 'password', autocomplete: 'off', spellcheck: 'false', autofocus: true }),
      KEY_HELP,
      32,
    )
    const id = field(
      'setup-id',
      'SteamID64',
      '🆔',
      h('input', { class: 'input mono input-num', inputmode: 'numeric', placeholder: ID_SHAPE }),
      ID_HELP,
      17,
    )
    this.keyField = key.f
    this.idField = id.f
    key.f.input.addEventListener('input', () => {
      this.render()
    })
    id.f.input.addEventListener('input', () => {
      this.idEdited = true
      this.render()
    })
    const form = h(
      'form',
      {
        class: 'stack',
        novalidate: true,
        onsubmit: (e: Event) => {
          e.preventDefault()
          this.touched = true
          this.render()
          if (!keyError(this.keyField.input.value) && !idError(this.idField.input.value)) void this.store()
        },
      },
      key.el,
      id.el,
      this.failure,
      h('div', { class: 'actions' }, this.submit),
    )
    this.root = card(null, form, { className: 'narrow' })
  }

  protected override setup(): void {
    this.replaceChildren(this.status, this.saved, this.root)
    this.keyField.input.focus()
    this.watch(q.setup)
  }

  protected update(): void {
    const { data, error } = q.setup.state
    this.status.replaceChildren(
      ...(error ? [errorNotice(error)] : []),
      ...(!data && !error ? [loading('setup')] : []),
      ...(data && !data.configured
        ? [notice('warning', null, spoken('Not configured yet', 'Every other screen needs these two values first.'))]
        : []),
    )
    // 🔒 + filled dots: a key is stored (typing replaces it); hollow dots: none yet.
    this.keyField.input.placeholder = data?.has_api_key ? KEY_STORED : KEY_SHAPE
    this.keyField.input.dataset.stored = String(data?.has_api_key ?? false)
    if (!this.idEdited) this.idField.input.value = data?.steam_id ?? ''
    this.render()
  }

  /** Everything that depends on the typed values or the save. */
  private render(): void {
    this.mark(this.keyField, keyError(this.keyField.input.value))
    this.mark(this.idField, idError(this.idField.input.value))
    this.saved.replaceChildren(
      ...(this.success
        ? [
            notice(
              'success',
              null,
              spoken('Saved', 'Steam accepted the key.'),
              h('a', { href: '/', class: 'btn btn-ghost btn-small', 'aria-label': 'Go to the dashboard' }, '🏠'),
            ),
          ]
        : []),
    )
    this.failure.replaceChildren(...(this.save.error ? [errorNotice(this.save.error)] : []))
    this.submit.disabled = this.save.pending
    // ⏳ while Steam checks, ✔️ to save; the words are spoken only.
    this.submit.replaceChildren(this.save.pending ? glyph('⏳', 'Checking with Steam…') : glyph('✔️', 'Save and verify'))
  }

  private mark(f: Field, problem: string | null): void {
    const bad = this.touched && problem !== null
    f.input.className = bad ? `${f.baseClass} input-bad` : f.baseClass
    f.input.setAttribute('aria-invalid', String(bad))
    // A bad value paints ⚠️ and how many characters it has of the `want` it needs.
    const count = `⚠️ ${f.input.value.trim().length}/${f.want}`
    const state = bad ? `${problem}|${count}` : 'ok'
    if (f.help.dataset.state === state) return
    f.help.dataset.state = state
    f.help.dataset.bad = String(bad)
    f.help.className = bad ? 'field-help text-danger' : 'field-help'
    f.help.replaceChildren()
    append(f.help, bad ? [h('span', { 'aria-hidden': 'true', class: 'mono' }, count), h('span', { class: 'sr-only' }, problem)] : f.hint())
  }

  private async store(): Promise<void> {
    this.success = false
    const out = await this.save.run()
    if (!out.ok) return
    this.success = true
    this.keyField.input.value = ''
    q.setup.set(out.value)
    invalidateAll()
    this.render()
  }
}

define('setup-form', SetupFormElement)
