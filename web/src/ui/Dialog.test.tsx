import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'

describe('Dialog', () => {
  it('opens modally and focuses the first field', () => {
    render(
      <Dialog open title="Ask" onClose={() => {}}>
        <input aria-label="field" />
      </Dialog>,
    )
    expect(screen.getByRole('dialog', { name: 'Ask' })).toHaveAttribute('open')
    expect(screen.getByLabelText('field')).toHaveFocus()
  })

  it('focuses the first action when there is no field', () => {
    render(
      <Dialog open title="Ask" onClose={() => {}}>
        <button type="button">Go</button>
      </Dialog>,
    )
    expect(screen.getByRole('button', { name: 'Go' })).toHaveFocus()
  })

  it('renders nothing inside while closed, and closes when open flips', () => {
    const { rerender, container } = render(
      <Dialog open title="Ask" onClose={() => {}}>
        <p>body</p>
      </Dialog>,
    )
    const el = container.querySelector('dialog')!
    expect(el.open).toBe(true)
    rerender(
      <Dialog open={false} title="Ask" onClose={() => {}}>
        <p>body</p>
      </Dialog>,
    )
    expect(el.open).toBe(false)
    expect(screen.queryByText('body')).toBeNull()
  })

  it('does not reopen an already open dialog', () => {
    const { rerender, container } = render(
      <Dialog open title="Ask" onClose={() => {}}>
        <p>a</p>
      </Dialog>,
    )
    const show = vi.spyOn(container.querySelector('dialog')!, 'showModal')
    rerender(
      <Dialog open title="Ask" onClose={() => {}} wide>
        <p>b</p>
      </Dialog>,
    )
    expect(show).not.toHaveBeenCalled()
    expect(container.querySelector('dialog')).toHaveClass('dialog-wide')
  })

  it('routes Escape and the close button through onClose', async () => {
    const onClose = vi.fn()
    const { container } = render(
      <Dialog open title="Ask" onClose={onClose}>
        <p>x</p>
      </Dialog>,
    )
    const cancel = new Event('cancel', { cancelable: true })
    container.querySelector('dialog')!.dispatchEvent(cancel)
    expect(cancel.defaultPrevented).toBe(true)
    expect(onClose).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('tolerates being a plain class when not wide', () => {
    const { container } = render(
      <Dialog open title="Ask" onClose={() => {}}>
        <p>x</p>
      </Dialog>,
    )
    expect(container.querySelector('dialog')).toHaveClass('dialog')
    expect(container.querySelector('dialog')).not.toHaveClass('dialog-wide')
    fireEvent.keyDown(document, { key: 'Escape' })
  })
})
