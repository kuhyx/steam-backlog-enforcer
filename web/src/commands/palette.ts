// `<command-palette>` (Ctrl/Cmd+K): every command from `GET /api/commands`
// plus the sections (was CommandPalette.tsx). A combobox + listbox pair:
// arrows move, Enter runs, Escape closes, and the active option is announced
// via aria-activedescendant.

import { q } from '../api/queries'
import { define, h } from '../lib/dom'
import { uid } from '../lib/ids'
import { pageHref, runner } from '../lib/runner'
import { NAV } from '../shell/nav'
import { errorNotice, loading, pill } from '../ui/build'
import { Modal } from '../ui/dialog'
import { COMMAND_HOME, commandLabel } from './catalog'

interface Entry {
  key: string
  title: string
  detail: string
  hint: string
  locked: string | null
  act: () => void
}

/** Navigate to a section page (a full page load: this is a static site). */
export function go(to: string): void {
  window.location.assign(pageHref(to))
}

export class CommandPaletteElement extends HTMLElement {
  private readonly modal = new Modal({ title: 'Command palette', onClose: () => { this.close() } })
  private readonly listId = uid('palette')
  private readonly input: HTMLInputElement
  private readonly list: HTMLUListElement
  private readonly status = h('div', { class: 'contents' })
  private active = 0
  private shown: Entry[] = []
  private unsubs: (() => void)[] = []
  private unwatch: (() => void) | null = null

  constructor() {
    super()
    this.input = h('input', {
      class: 'input palette-input',
      role: 'combobox',
      'aria-expanded': 'true',
      'aria-controls': `${this.listId}-list`,
      'aria-label': 'Search commands',
      placeholder: 'Type a command or section…',
      autofocus: true,
    })
    this.list = h('ul', { id: `${this.listId}-list`, role: 'listbox', class: 'palette-list', 'aria-label': 'Commands' })
    this.input.addEventListener('input', () => {
      this.active = 0
      this.renderList()
    })
    this.input.addEventListener('keydown', (e) => {
      this.onKey(e)
    })
    this.modal.render(this.input, this.status, this.list, h('p', { class: 'field-help' }, '↑↓ to move · Enter to run · Esc to close'))
  }

  get isOpen(): boolean {
    return this.modal.isOpen
  }

  connectedCallback(): void {
    this.append(this.modal.el)
    this.unsubs.push(runner.onPalette(() => {
      this.open()
    }))
    this.unsubs.push(runner.onRun(() => {
      this.close()
    }))
  }

  disconnectedCallback(): void {
    this.close()
    for (const u of this.unsubs.splice(0)) u()
  }

  toggle(): void {
    if (this.isOpen) this.close()
    else this.open()
  }

  open(): void {
    if (this.isOpen) return
    this.input.value = ''
    this.active = 0
    this.unwatch = q.commands.subscribe(() => {
      this.renderList()
    })
    this.renderList()
    this.modal.show()
    this.input.focus()
  }

  close(): void {
    this.unwatch?.()
    this.unwatch = null
    this.modal.hide()
  }

  private entries(): Entry[] {
    return [
      ...(q.commands.state.data ?? []).map((c) => ({
        key: c.name,
        title: commandLabel(c.name),
        detail: c.description,
        hint: c.kind === 'job' ? (c.friction ? 'run · confirm' : 'run') : `open ${COMMAND_HOME[c.name]}`,
        locked: c.locked_reason,
        act: () => {
          if (c.kind === 'job') runner.run(c.name)
          else {
            this.close()
            go(COMMAND_HOME[c.name])
          }
        },
      })),
      ...NAV.map((n) => ({
        key: `nav:${n.to}`,
        title: `Go to ${n.label}`,
        detail: n.blurb,
        hint: 'navigate',
        locked: null,
        act: () => {
          this.close()
          go(n.to)
        },
      })),
    ]
  }

  private renderList(): void {
    const { data, error } = q.commands.state
    this.status.replaceChildren(...(error ? [errorNotice(error)] : !data ? [loading('commands')] : []))
    const needle = this.input.value.trim().toLowerCase()
    const all = this.entries()
    this.shown = needle ? all.filter((e) => `${e.key} ${e.title} ${e.detail}`.toLowerCase().includes(needle)) : all
    this.active = Math.min(this.active, Math.max(0, this.shown.length - 1))
    this.list.replaceChildren(
      ...this.shown.map((e, i) => {
        const li = h(
          'li',
          { id: `${this.listId}-${i}`, role: 'option', 'aria-selected': String(i === this.active), class: i === this.active ? 'palette-item active' : 'palette-item' },
          h('span', { class: 'palette-title' }, e.title, e.locked ? pill('warning', 'locked') : null),
          h('span', { class: 'palette-detail' }, e.locked ?? e.detail),
          h('span', { class: 'palette-hint' }, e.hint),
        )
        li.addEventListener('mousemove', () => {
          if (this.active !== i) this.setActive(i)
        })
        li.addEventListener('click', e.act)
        return li
      }),
    )
    if (this.shown.length === 0) this.list.append(h('li', { class: 'empty' }, `No command matches “${this.input.value}”.`))
    this.syncActive()
  }

  private setActive(i: number): void {
    this.active = i
    this.list.querySelectorAll('[role=option]').forEach((li, j) => {
      li.setAttribute('aria-selected', String(j === i))
      li.className = j === i ? 'palette-item active' : 'palette-item'
    })
    this.syncActive()
  }

  private syncActive(): void {
    if (this.shown.length > 0) this.input.setAttribute('aria-activedescendant', `${this.listId}-${this.active}`)
    else this.input.removeAttribute('aria-activedescendant')
  }

  private onKey(e: KeyboardEvent): void {
    const last = this.shown.length - 1
    const moves = new Map<string, number>([
      ['ArrowDown', Math.min(last, this.active + 1)],
      ['ArrowUp', Math.max(0, this.active - 1)],
      ['PageDown', Math.min(last, this.active + 8)],
      ['PageUp', Math.max(0, this.active - 8)],
    ])
    const to = moves.get(e.key)
    if (to !== undefined) {
      e.preventDefault()
      this.setActive(to)
      document.getElementById(`${this.listId}-${to}`)?.scrollIntoView({ block: 'nearest' })
    } else if (e.key === 'Enter') {
      const entry = this.shown.at(this.active)
      if (!entry) return
      e.preventDefault()
      entry.act()
    }
  }
}

define('command-palette', CommandPaletteElement)
