// Typed-phrase friction (was PhraseField.tsx). Shows the exact sentence, then
// live per-character feedback on the typed text. Paste is blocked: retyping
// is the friction. The server re-checks; this field only helps get it right.
// The input is built once, so typing never loses focus or caret position.

import { h } from '../lib/dom'
import { uid } from '../lib/ids'
import { phraseMatches } from './catalog'

export interface PhraseFieldOptions {
  phrase: string
  value?: string
  label?: string
  autofocus?: boolean
  onChange: (value: string) => void
}

export class PhraseField {
  readonly el: HTMLDivElement
  readonly input: HTMLInputElement
  private readonly target: HTMLParagraphElement
  private readonly status: HTMLParagraphElement
  private readonly phrase: string

  constructor({ phrase, value = '', label = 'Type the phrase to confirm', autofocus = false, onChange }: PhraseFieldOptions) {
    this.phrase = phrase
    const id = uid('phrase')
    this.target = h('p', { class: 'phrase-target', 'aria-hidden': 'true' })
    this.status = h('p', { id: `${id}-status`, 'aria-live': 'polite' })
    this.input = h('input', {
      id,
      value,
      autocomplete: 'off',
      spellcheck: 'false',
      autofocus,
      'aria-describedby': `${id}-status`,
    })
    this.input.value = value
    const block = (e: Event) => {
      e.preventDefault()
    }
    this.input.addEventListener('paste', block)
    this.input.addEventListener('drop', block)
    this.input.addEventListener('input', () => {
      this.refresh()
      onChange(this.input.value)
    })
    this.el = h(
      'div',
      { class: 'phrase' },
      h('label', { for: id, class: 'field-label' }, h('span', { 'aria-hidden': 'true' }, '⌨️'), h('span', { class: 'sr-only' }, label)),
      this.target,
      this.input,
      h('p', { class: 'sr-only' }, `Phrase: ${phrase}`),
      this.status,
    )
    this.refresh()
  }

  get value(): string {
    return this.input.value
  }

  private refresh(): void {
    const typed = this.input.value.trim()
    const ok = phraseMatches(this.phrase, this.input.value)
    const prefixOk = this.phrase.startsWith(typed)
    this.target.replaceChildren(
      ...Array.from(this.phrase).map((ch, i) => h('span', { class: i < typed.length ? (typed[i] === ch ? 'ok' : 'bad') : null }, ch)),
    )
    this.input.className = `input mono ${ok ? 'input-ok' : prefixOk ? '' : 'input-bad'}`.trim()
    this.input.setAttribute('aria-invalid', String(!prefixOk))
    this.status.className = `field-help ${ok ? 'text-success' : prefixOk ? '' : 'text-danger'}`.trim()
    // Textgate: ✅ / count / ❌ painted; the sentence is spoken only.
    const [mark, spoken] = ok
      ? ['✅', 'Matches.']
      : prefixOk
        ? [`${typed.length}/${this.phrase.length}`, `${typed.length} of ${this.phrase.length} characters`]
        : ['❌', 'Does not match — check case and spacing.']
    this.status.replaceChildren(h('span', { 'aria-hidden': 'true' }, mark), h('span', { class: 'sr-only' }, spoken))
  }
}
