// The dialog's close button is a registered icon: his word beside it, his
// glyph in place of the default, the aria-label stays "Close".

import { describe, expect, it, vi } from 'vitest'
import { useIcons } from '../test/iconLedger'
import { Modal } from './dialog'

describe('Modal close button by id', () => {
  it('paints the default cross, spoken name Close', () => {
    const modal = new Modal({ title: 'Hello', onClose: vi.fn() })
    const close = modal.el.querySelector('.dialog-close')
    expect(close?.textContent).toBe('×')
    expect(close).toHaveAttribute('aria-label', 'Close')
  })

  it('paints the user word right of his chosen glyph', () => {
    useIcons({ 'dialog.close': { word: 'exit', glyph: '❌' } })
    const modal = new Modal({ title: 'Hello', onClose: vi.fn() })
    const close = modal.el.querySelector('.dialog-close')
    expect(close?.textContent).toBe('❌Exit')
    expect(close?.querySelector('.icon-word')).toHaveAttribute('data-icon-word', 'dialog.close')
    expect(close).toHaveAttribute('aria-label', 'Close')
  })
})
