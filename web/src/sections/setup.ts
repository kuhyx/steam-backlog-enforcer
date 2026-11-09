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
import { card, errorNotice, loading, notice } from '../ui/build'

const KEY_RE = /^[0-9A-Fa-f]{32}$/
const ID_RE = /^7656\d{13}$/

export function keyError(key: string): string | null {
  return KEY_RE.test(key.trim()) ? null : 'The key is 32 hexadecimal characters.'
}

export function idError(id: string): string | null {
  return ID_RE.test(id.trim()) ? null : 'A SteamID64 is 17 digits and starts with 7656.'
}

const KEY_HELP = (): Child[] => [
  'Get one at ',
  h('a', { href: 'https://steamcommunity.com/dev/apikey', target: '_blank', rel: 'noreferrer' }, 'steamcommunity.com/dev/apikey'),
  '. It is never shown again.',
]
const ID_HELP = (): Child[] => ['Your profile URL or steamid.io shows it.']

interface Field {
  input: HTMLInputElement
  help: HTMLParagraphElement
  hint: () => Child[]
  baseClass: string
}

function field(id: string, label: string, input: HTMLInputElement, hint: () => Child[]): { el: HTMLDivElement; f: Field } {
  const help = h('p', { id: `${id}-help`, class: 'field-help' }, hint())
  input.id = id
  input.setAttribute('aria-describedby', `${id}-help`)
  return {
    el: h('div', { class: 'form-field' }, h('label', { for: id, class: 'field-label' }, label), input, help),
    f: { input, help, hint, baseClass: input.className },
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
      h('input', { class: 'input mono', type: 'password', autocomplete: 'off', spellcheck: 'false', autofocus: true }),
      KEY_HELP,
    )
    const id = field('setup-id', 'SteamID64', h('input', { class: 'input mono input-num', inputmode: 'numeric' }), ID_HELP)
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
        ? [notice('warning', 'Not configured yet', 'Every other screen needs these two values first.')]
        : []),
    )
    this.keyField.input.placeholder = data?.has_api_key ? 'A key is stored — type a new one to replace it' : '32 hex characters'
    if (!this.idEdited) this.idField.input.value = data?.steam_id ?? ''
    this.render()
  }

  /** Everything that depends on the typed values or the save. */
  private render(): void {
    this.mark(this.keyField, keyError(this.keyField.input.value))
    this.mark(this.idField, idError(this.idField.input.value))
    this.saved.replaceChildren(
      ...(this.success
        ? [notice('success', 'Saved', 'Steam accepted the key. ', h('a', { href: '/' }, 'Go to the dashboard'), '.')]
        : []),
    )
    this.failure.replaceChildren(...(this.save.error ? [errorNotice(this.save.error)] : []))
    this.submit.disabled = this.save.pending
    this.submit.textContent = this.save.pending ? 'Checking with Steam…' : 'Save and verify'
  }

  private mark(f: Field, problem: string | null): void {
    const bad = this.touched && problem !== null
    f.input.className = bad ? `${f.baseClass} input-bad` : f.baseClass
    f.input.setAttribute('aria-invalid', String(bad))
    const shown = f.help.dataset.bad === String(bad) && (!bad || f.help.textContent === problem)
    if (shown) return
    f.help.dataset.bad = String(bad)
    f.help.className = bad ? 'field-help text-danger' : 'field-help'
    f.help.replaceChildren()
    append(f.help, bad ? problem : f.hint())
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
