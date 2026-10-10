import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { LibraryGame } from '../api/contract'
import { makeLibGame } from '../test/fixtures'
import { SearchBox } from './SearchBox'

const A = makeLibGame({ app_id: 1, name: 'Alpha' })
const B = makeLibGame({ app_id: 2, name: 'Beta', ineligible_reason: 'Already finished' })
const C = makeLibGame({ app_id: 3, name: 'Gamma' })

function Harness({ suggestions = [A, B, C], onChoose = () => {} }: { suggestions?: LibraryGame[]; onChoose?: (g: LibraryGame) => void }) {
  const [value, setValue] = useState('')
  return (
    <SearchBox value={value} onChange={setValue} suggestions={suggestions} reason={(g) => g.ineligible_reason} onChoose={onChoose} />
  )
}

const box = () => screen.getByRole('combobox', { name: 'Search your games' })

describe('SearchBox', () => {
  it('lists suggestions once typing starts, with reason or meta line', async () => {
    render(<Harness />)
    expect(screen.queryByRole('option')).toBeNull()
    await userEvent.type(box(), 'a')
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(3)
    expect(options[1]).toHaveTextContent('Already finished')
    expect(options[0]).toHaveTextContent('50%')
    expect(box()).toHaveAttribute('aria-expanded', 'true')
  })

  it('stays closed when there are no suggestions', async () => {
    render(<Harness suggestions={[]} />)
    await userEvent.type(box(), 'zz')
    expect(box()).toHaveAttribute('aria-expanded', 'false')
  })

  it('moves through the list with the arrows, wrapping, and announces the active one', async () => {
    render(<Harness />)
    await userEvent.type(box(), 'a')
    await userEvent.keyboard('{ArrowDown}')
    expect(box()).toHaveAttribute('aria-activedescendant', expect.stringMatching(/-0$/))
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('starts from the last suggestion on ArrowUp, and reopens a closed list', async () => {
    render(<Harness />)
    await userEvent.type(box(), 'a')
    await userEvent.keyboard('{Escape}')
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.keyboard('{ArrowUp}')
    expect(box()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('ignores arrows with no suggestions', async () => {
    render(<Harness suggestions={[]} />)
    await userEvent.type(box(), 'a')
    await userEvent.keyboard('{ArrowDown}{ArrowUp}')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
  })

  it('Enter chooses the highlighted suggestion, else the first, and closes the list', async () => {
    const onChoose = vi.fn()
    render(<Harness onChoose={onChoose} />)
    await userEvent.type(box(), 'a')
    await userEvent.keyboard('{Enter}')
    expect(onChoose).toHaveBeenLastCalledWith(A)
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.type(box(), 'b')
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onChoose).toHaveBeenLastCalledWith(B)
  })

  it('falls back to the first suggestion when the highlight is out of range', () => {
    const onChoose = vi.fn()
    const { rerender } = render(<Harness onChoose={onChoose} />)
    fireEvent.change(box(), { target: { value: 'a' } })
    fireEvent.keyDown(box(), { key: 'ArrowUp' }) // highlights the last of three
    rerender(<Harness onChoose={onChoose} suggestions={[A]} />)
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(onChoose).toHaveBeenCalledWith(A)
  })

  it('Enter does nothing while the list is hidden', async () => {
    const onChoose = vi.fn()
    render(<Harness onChoose={onChoose} />)
    await userEvent.type(box(), '{Enter}')
    expect(onChoose).not.toHaveBeenCalled()
  })

  it('Escape closes the list first, then clears the text, then lets the key go', async () => {
    const outer = vi.fn()
    render(
      <div onKeyDown={outer}>
        <Harness />
      </div>,
    )
    await userEvent.type(box(), 'abc')
    await userEvent.keyboard('{Escape}')
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    expect(box()).toHaveValue('abc')
    await userEvent.keyboard('{Escape}')
    expect(box()).toHaveValue('')
    outer.mockClear()
    await userEvent.keyboard('{Escape}')
    expect(outer).toHaveBeenCalled()
  })

  it('opens on focus and closes on blur', async () => {
    render(<Harness />)
    await userEvent.type(box(), 'a')
    await userEvent.tab()
    expect(box()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(box())
    expect(box()).toHaveAttribute('aria-expanded', 'true')
  })

  it('chooses a suggestion on mousedown, before blur can close the list', async () => {
    const onChoose = vi.fn()
    render(<Harness onChoose={onChoose} />)
    await userEvent.type(box(), 'a')
    fireEvent.mouseDown(screen.getByRole('option', { name: /Gamma/ }))
    expect(onChoose).toHaveBeenCalledWith(C)
  })
})
