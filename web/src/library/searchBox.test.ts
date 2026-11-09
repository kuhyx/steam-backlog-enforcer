import { fireEvent, screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { LibraryGame } from '../api/contract'
import { makeLibGame } from '../test/fixtures'
import { SearchBox } from './searchBox'

const A = makeLibGame({ app_id: 1, name: 'Alpha' })
const B = makeLibGame({ app_id: 2, name: 'Beta', ineligible_reason: 'Already finished' })
const C = makeLibGame({ app_id: 3, name: 'Gamma' })

/** A box whose owner answers every edit with `suggestions`, as the browser does. */
function setup(suggestions: LibraryGame[] = [A, B, C], parent: HTMLElement = document.body) {
  const onChoose = vi.fn()
  const onInput = vi.fn()
  const box: SearchBox = new SearchBox({
    onInput: (v) => {
      onInput(v)
      box.setSuggestions(v.trim() ? suggestions : [])
    },
    onChoose,
    reason: (g) => g.ineligible_reason,
  })
  parent.append(box.el)
  return { box, onChoose, onInput }
}

const input = () => screen.getByRole('combobox', { name: 'Search your games' })

describe('SearchBox', () => {
  it('lists suggestions once typing starts, with reason or meta line', async () => {
    setup()
    expect(screen.queryByRole('option')).toBeNull()
    await userEvent.type(input(), 'a')
    const options = screen.getAllByRole('option')
    expect(options).toHaveLength(3)
    expect(options[1]).toHaveTextContent('Already finished')
    expect(options[0]).toHaveTextContent('50%')
    expect(input()).toHaveAttribute('aria-expanded', 'true')
    expect(input()).toHaveAttribute('aria-controls', screen.getByRole('listbox').id)
  })

  it('reports every edit and keeps the same input node', async () => {
    const { onInput, box } = setup()
    const node = input()
    await userEvent.type(node, 'ab')
    expect(onInput.mock.calls).toEqual([['a'], ['ab']])
    expect(input()).toBe(node)
    expect(box.value).toBe('ab')
  })

  it('stays closed when there are no suggestions', async () => {
    setup([])
    await userEvent.type(input(), 'zz')
    expect(input()).toHaveAttribute('aria-expanded', 'false')
  })

  it('moves through the list with the arrows, wrapping, and announces the active one', async () => {
    setup()
    await userEvent.type(input(), 'a')
    await userEvent.keyboard('{ArrowDown}')
    expect(input()).toHaveAttribute('aria-activedescendant', expect.stringMatching(/-0$/) as string)
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('option')[0]).toHaveClass('active')
    await userEvent.keyboard('{ArrowUp}')
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('starts from the last suggestion on ArrowUp, and reopens a closed list', async () => {
    setup()
    await userEvent.type(input(), 'a')
    await userEvent.keyboard('{Escape}')
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.keyboard('{ArrowUp}')
    expect(input()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')
  })

  it('ignores arrows with no suggestions', async () => {
    setup([])
    await userEvent.type(input(), 'a')
    await userEvent.keyboard('{ArrowDown}{ArrowUp}')
    expect(input()).not.toHaveAttribute('aria-activedescendant')
  })

  it('Enter chooses the highlighted suggestion, else the first, and closes the list', async () => {
    const { onChoose } = setup()
    await userEvent.type(input(), 'a')
    await userEvent.keyboard('{Enter}')
    expect(onChoose).toHaveBeenLastCalledWith(A)
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.type(input(), 'b')
    await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onChoose).toHaveBeenLastCalledWith(B)
  })

  it('falls back to the first suggestion when the highlight is out of range', () => {
    const { box, onChoose } = setup()
    fireEvent.input(input(), { target: { value: 'a' } })
    fireEvent.keyDown(input(), { key: 'ArrowUp' }) // highlights the last of three
    box.setSuggestions([A])
    fireEvent.keyDown(input(), { key: 'Enter' })
    expect(onChoose).toHaveBeenCalledWith(A)
  })

  it('Enter does nothing while the list is hidden', async () => {
    const { onChoose } = setup()
    await userEvent.type(input(), '{Enter}')
    await userEvent.type(input(), 'a{Escape}{Enter}')
    expect(onChoose).not.toHaveBeenCalled()
  })

  it('Escape closes the list first, then clears the text, then lets the key go', async () => {
    const outer = vi.fn()
    const wrap = document.body.appendChild(document.createElement('div'))
    wrap.addEventListener('keydown', outer)
    const { onInput } = setup(undefined, wrap)
    await userEvent.type(input(), 'abc')
    outer.mockClear()
    await userEvent.keyboard('{Escape}')
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    expect(input()).toHaveValue('abc')
    expect(outer).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    expect(input()).toHaveValue('')
    expect(onInput).toHaveBeenLastCalledWith('')
    expect(outer).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    expect(outer).toHaveBeenCalled()
  })

  it('leaves other keys alone', () => {
    setup()
    const e = new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true })
    input().dispatchEvent(e)
    expect(e.defaultPrevented).toBe(false)
  })

  it('opens on focus and closes on blur', async () => {
    setup()
    await userEvent.type(input(), 'a')
    await userEvent.tab()
    expect(input()).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(input())
    expect(input()).toHaveAttribute('aria-expanded', 'true')
  })

  it('sets the text without reporting it or opening the list', () => {
    const { box, onInput } = setup()
    box.setSuggestions([A])
    box.value = 'restored'
    expect(input()).toHaveValue('restored')
    expect(onInput).not.toHaveBeenCalled()
    expect(input()).toHaveAttribute('aria-expanded', 'false')
  })

  it('chooses a suggestion on mousedown, before blur can close the list', async () => {
    const { onChoose } = setup()
    await userEvent.type(input(), 'a')
    fireEvent.mouseDown(screen.getByRole('option', { name: /Gamma/ }))
    expect(onChoose).toHaveBeenCalledWith(C)
  })
})
