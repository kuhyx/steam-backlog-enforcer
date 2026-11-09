import { describe, expect, it, vi } from 'vitest'
import { h } from '../lib/dom'
import { Modal } from './dialog'

function make(over: { wide?: boolean } = {}) {
  const onClose = vi.fn()
  const modal = new Modal({ title: 'Hello', onClose, ...over })
  document.body.append(modal.el)
  return { modal, onClose }
}

describe('Modal', () => {
  it('labels the dialog and marks wide ones', () => {
    const { modal } = make()
    expect(modal.el.getAttribute('aria-label')).toBe('Hello')
    expect(modal.el.className).toBe('dialog')
    expect(make({ wide: true }).modal.el.className).toBe('dialog dialog-wide')
  })

  it('opens once, focuses the first field, and restores focus on hide', () => {
    const { modal } = make()
    const opener = h('button', {}, 'open')
    document.body.append(opener)
    opener.focus()
    modal.render(h('input', { id: 'f' }), h('button', {}, 'go'))
    modal.show()
    expect(modal.isOpen).toBe(true)
    expect(document.activeElement?.id).toBe('f')
    modal.show()
    modal.hide()
    expect(modal.isOpen).toBe(false)
    expect(document.activeElement).toBe(opener)
    modal.hide()
  })

  it('focuses the first action when there is no field, never the close button', () => {
    const { modal } = make()
    modal.render(h('button', { id: 'act' }, 'go'))
    modal.show()
    expect(document.activeElement?.id).toBe('act')
  })

  it('focus-first is a no-op for an empty dialog', () => {
    const { modal } = make()
    expect(() => {
      modal.show()
    }).not.toThrow()
  })

  it('hides without restoring focus when it was opened elsewhere', () => {
    const { modal } = make()
    modal.el.setAttribute('open', '')
    modal.hide()
    expect(modal.isOpen).toBe(false)
  })

  it('routes the close button and Escape through onClose', () => {
    const { modal, onClose } = make()
    modal.el.querySelector<HTMLButtonElement>('.dialog-close')?.click()
    expect(onClose).toHaveBeenCalledTimes(1)
    const cancel = new Event('cancel', { cancelable: true })
    modal.el.dispatchEvent(cancel)
    expect(cancel.defaultPrevented).toBe(true)
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('renders below the header and retitles', () => {
    const { modal } = make()
    modal.render(h('p', {}, 'one'))
    modal.render([h('p', {}, 'two')], 'tail')
    expect(modal.body.textContent).toContain('two')
    expect(modal.body.textContent).not.toContain('one')
    expect(modal.body.querySelector('h2')?.textContent).toBe('Hello')
    modal.setTitle('New')
    expect(modal.body.querySelector('h2')?.textContent).toBe('New')
    expect(modal.el.getAttribute('aria-label')).toBe('New')
  })
})
