// Native `<dialog>` in modal mode: the browser supplies the focus trap, the
// inert background and Escape (routed through `onClose` so the owner decides
// what closing means). Focus returns to the opener when it closes.

import { append, h, type Child } from '../lib/dom'

export interface ModalOptions {
  title: string
  wide?: boolean
  onClose: () => void
}

export class Modal {
  readonly el: HTMLDialogElement
  readonly body: HTMLDivElement
  private readonly heading: HTMLHeadingElement
  private readonly head: HTMLElement
  private opener: Element | null = null

  constructor({ title, wide = false, onClose }: ModalOptions) {
    // Textgate: the title is spoken only; the dialog's content says what it is.
    this.heading = h('h2', { class: 'sr-only' }, title)
    const close = h(
      'button',
      { type: 'button', class: 'btn btn-ghost btn-icon dialog-close', 'aria-label': 'Close', onclick: onClose },
      h('span', { 'aria-hidden': 'true' }, '×'),
    )
    this.head = h('header', { class: 'dialog-head' }, this.heading, close)
    this.body = h('div', { class: 'dialog-body' }, this.head)
    this.el = h('dialog', { class: wide ? 'dialog dialog-wide' : 'dialog', 'aria-label': title }, this.body)
    this.el.addEventListener('cancel', (e) => {
      e.preventDefault()
      onClose()
    })
  }

  get isOpen(): boolean {
    return this.el.open
  }

  setTitle(title: string): void {
    this.heading.textContent = title
    this.el.setAttribute('aria-label', title)
  }

  /** Replace everything below the dialog's header. */
  render(...children: Child[]): void {
    this.body.replaceChildren(this.head)
    append(this.body, children)
  }

  show(): void {
    if (this.el.open) return
    this.opener = document.activeElement
    this.el.showModal()
    this.focusFirst()
  }

  /** Move focus to the first field, else the first action: what every dialog here wants. */
  focusFirst(): void {
    this.el
      .querySelector<HTMLElement>(
        '[autofocus], input:not([disabled]):not([type=hidden]), textarea, select, .dialog-body button:not(.dialog-close):not([disabled])',
      )
      ?.focus()
  }

  hide(): void {
    if (!this.el.open) return
    this.el.close()
    if (this.opener instanceof HTMLElement) this.opener.focus()
    this.opener = null
  }
}
