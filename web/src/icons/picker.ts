// `<icon-words-picker>` on /words, after cleanup-plate's icon-word picker:
// one icon at a time, big and as it looks in place, with what it is and does,
// three suggested words, a field for your own words, a skip, and three
// alternative glyphs. Every choice is saved at once (POST /api/icon-words/…);
// a word or a skip advances, a glyph swap stays so you see it. It opens on the
// first unanswered icon; going back shows what you saved.
// Keys: 1 2 3 pick, O own word (Enter saves, Esc leaves the field), S skip,
// 6 default glyph, 7 8 9 alternatives, ←/→ move. Keys never fire while you
// type, with Alt/Ctrl/Meta held (Alt+digit is the section nav) or under a
// dialog (the command palette).

import { request } from '../api/client'
import { ICON_WORDS_ENDPOINTS, type IconChoiceUpdate, type IconLedger } from '../api/iconWordsContract'
import { define } from '../lib/dom'
import { loading } from '../ui/build'
import { isAnswered, setLedger, setWordsHidden, wordsHidden } from './ledger'
import { pickerStatus, pickerView, type PickerHandlers } from './pickerView'
import { ICONS } from './registry'
import { decorateChrome } from './render'
import { normalizeWord, wordProblem } from './wordRules'

function firstUnanswered(): number {
  const i = ICONS.findIndex((e) => !isAnswered(e.id))
  return i === -1 ? ICONS.length : i
}

/** A text field has the keys while focused; a checkbox does not. */
function typing(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement && target.type !== 'checkbox'
}

export class IconWordsPickerElement extends HTMLElement {
  private index = 0
  private loaded = false
  private error: unknown = null
  private invalid = false
  private draft: string | null = null
  private readonly onKey = (e: KeyboardEvent): void => {
    this.key(e)
  }

  private readonly handlers: PickerHandlers = {
    word: (slot) => { this.pick(slot) },
    own: (text) => { this.own(text) },
    skip: () => { void this.commit({ word: null }, true) },
    glyph: (slot) => { this.glyph(slot) },
    go: (to) => { this.go(to) },
    jump: () => { this.go(firstUnanswered()) },
    showWords: (on) => {
      setWordsHidden(!on)
      decorateChrome()
      this.render()
    },
  }

  private readonly keys = new Map<string, () => void>([
    ['1', () => { this.pick(0) }],
    ['2', () => { this.pick(1) }],
    ['3', () => { this.pick(2) }],
    ['6', () => { this.glyph(null) }],
    ['7', () => { this.glyph(0) }],
    ['8', () => { this.glyph(1) }],
    ['9', () => { this.glyph(2) }],
    ['o', () => { this.focusOwn() }],
    ['O', () => { this.focusOwn() }],
    ['s', this.handlers.skip],
    ['S', this.handlers.skip],
    ['ArrowLeft', () => { this.go(this.index - 1) }],
    ['ArrowRight', () => { this.go(this.index + 1) }],
  ])

  connectedCallback(): void {
    document.addEventListener('keydown', this.onKey)
    this.replaceChildren(loading('icon words'))
    request<IconLedger>('GET', ICON_WORDS_ENDPOINTS.ledger).then(
      (ledger) => {
        setLedger(ledger)
        this.loaded = true
        this.go(firstUnanswered())
      },
      (e: unknown) => {
        this.replaceChildren(pickerStatus(e))
      },
    )
  }

  disconnectedCallback(): void {
    document.removeEventListener('keydown', this.onKey)
  }

  /** The shown icon; undefined on the summary page after the last one. */
  private get entry() {
    return ICONS.at(this.index)
  }

  private go(to: number): void {
    this.index = Math.min(Math.max(0, to), ICONS.length)
    this.error = null
    this.invalid = false
    this.draft = null
    this.render()
  }

  private focusOwn(): void {
    this.querySelector<HTMLInputElement>('input[name=own]')?.focus()
  }

  private pick(slot: number): void {
    const word = this.entry?.words[slot]
    if (word !== undefined) void this.commit({ word }, true)
  }

  private glyph(slot: number | null): void {
    const entry = this.entry
    if (!entry) return
    void this.commit({ glyph: slot === null ? null : entry.alts[slot] }, false)
  }

  private own(text: string): void {
    if (wordProblem(text)) {
      this.draft = text
      this.invalid = true
      this.render()
      return
    }
    void this.commit({ word: normalizeWord(text) }, true)
  }

  private async commit(update: IconChoiceUpdate, advance: boolean): Promise<void> {
    const entry = this.entry
    if (!entry) return
    try {
      setLedger(await request<IconLedger>('POST', ICON_WORDS_ENDPOINTS.icon(entry.id), update))
      decorateChrome()
      this.go(advance ? this.index + 1 : this.index)
    } catch (e) {
      const word = (update as { word?: unknown }).word
      this.error = e
      this.invalid = (e as { code?: string }).code === 'invalid_params'
      this.draft = typeof word === 'string' ? word : null
      this.render()
    }
  }

  private key(e: KeyboardEvent): void {
    const act = this.keys.get(e.key)
    if (!act || !this.loaded || e.altKey || e.ctrlKey || e.metaKey || typing(e.target)) return
    if (document.querySelector('dialog[open]')) return
    e.preventDefault()
    act()
  }

  private render(): void {
    this.replaceChildren(
      ...pickerView(
        {
          index: this.index,
          total: ICONS.length,
          answered: ICONS.filter((e) => isAnswered(e.id)).length,
          entry: this.entry ?? null,
          error: this.error,
          invalid: this.invalid,
          draft: this.draft,
          wordsShown: !wordsHidden(),
        },
        this.handlers,
      ),
    )
  }
}

define('icon-words-picker', IconWordsPickerElement)
