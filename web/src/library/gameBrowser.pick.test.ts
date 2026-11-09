import { screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { define } from '../lib/dom'
import { card, grid, render, search, titles, withLibrary } from '../test/browserHelpers'
import { GameBrowser } from './gameBrowser'
import type { GameBrowserElement, PickMode } from './pick'

describe('GameBrowser pick mode', () => {
  beforeEach(() => {
    withLibrary()
  })

  const pickable = new Set([1, 2])
  const setup = (selected: number | null = null) => {
    const onSelect = vi.fn()
    const el = render({ appIds: pickable, selected, onSelect })
    return { onSelect, el }
  }

  it('selects eligible cards only, and never submits', async () => {
    const { onSelect } = setup()
    await screen.findByText('5 of 5 games')
    await userEvent.click(card('The Witcher 2'))
    expect(onSelect).toHaveBeenCalledWith(2)
    onSelect.mockClear()
    await userEvent.click(card('Hollow Knight'))
    await userEvent.click(card('The Witcher 3'))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('shows why a game is not offered', async () => {
    setup(2)
    await screen.findByText('5 of 5 games')
    expect(card('The Witcher 3')).toHaveTextContent('Already started')
    expect(card('Hollow Knight')).toHaveTextContent('Not offered here')
    expect(card('The Witcher 2')).toHaveAttribute('aria-pressed', 'true')
    expect(card('Hollow Knight')).toHaveAttribute('aria-disabled', 'true')
  })

  it('"pickable only" keeps just the ids the job sent', async () => {
    setup()
    await screen.findByText('5 of 5 games')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Pickable only' }))
    await waitFor(() => {
      expect(titles()).toEqual(['The Witcher', 'The Witcher 2'])
    })
  })

  it('choosing a suggestion selects an eligible game but only focuses an ineligible one', async () => {
    const { onSelect } = setup()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'hollow')
    await userEvent.keyboard('{Enter}')
    expect(onSelect).not.toHaveBeenCalled()
    await waitFor(() => {
      expect(card('Hollow Knight')).toHaveFocus()
    })
    await userEvent.clear(search())
    await userEvent.type(search(), 'witcher 2')
    await userEvent.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(2)
    await waitFor(() => {
      expect(card('The Witcher 2')).toHaveFocus()
    })
  })

  it('a new `selected` moves the highlight without rebuilding the toolbar or grid', async () => {
    const { el } = setup(1)
    await screen.findByText('5 of 5 games')
    const input = search()
    const cards = [...grid().children]
    const pick: PickMode = { appIds: pickable, selected: 1, onSelect: vi.fn() }
    el.pick = pick
    el.pick = { ...pick, selected: 2 }
    expect(card('The Witcher 2')).toHaveAttribute('aria-pressed', 'true')
    expect(card('The Witcher 2')).toHaveClass('selected')
    expect(card('The Witcher')).toHaveAttribute('aria-pressed', 'false')
    el.pick = { ...pick, selected: null }
    expect(grid().querySelectorAll('.selected')).toHaveLength(0)
    expect(search()).toBe(input)
    expect([...grid().children]).toEqual(cards)
  })

  it('works as the job prompt drives it: onSelect sets `pick` re-entrantly', async () => {
    const el = render()
    const pick: PickMode = {
      appIds: pickable,
      selected: null,
      onSelect: (id) => {
        el.pick = { ...pick, selected: id }
      },
    }
    el.pick = pick
    await screen.findByText('5 of 5 games')
    await userEvent.click(card('The Witcher 2'))
    expect(card('The Witcher 2')).toHaveAttribute('aria-pressed', 'true')
    expect(el.pick).toMatchObject({ selected: 2 })
  })

  it('new ids, or leaving pick mode, repaint every card', async () => {
    const { el } = setup()
    await screen.findByText('5 of 5 games')
    el.pick = { appIds: new Set([5]), selected: 5, onSelect: vi.fn() }
    await waitFor(() => {
      expect(card('Hollow Knight')).toHaveAttribute('aria-pressed', 'true')
    })
    expect(card('The Witcher 2')).toHaveTextContent('Not offered here')
    el.pick = null
    await waitFor(() => {
      expect(card('Hollow Knight')).not.toHaveAttribute('aria-pressed')
    })
    expect(card('The Witcher 2')).not.toHaveTextContent('Not offered here')
    expect(card('The Witcher 3')).toHaveTextContent('Already started')
    expect(el.pick).toBeNull()
  })

  it('accepts `pick` set before the element is connected', async () => {
    const el = document.createElement('game-browser') as GameBrowserElement
    el.pick = { appIds: pickable, selected: 1, onSelect: vi.fn() }
    document.body.append(el)
    await screen.findByText('5 of 5 games')
    expect(card('The Witcher')).toHaveAttribute('aria-pressed', 'true')
  })

  it('accepts `pick` set before the tag is even defined', async () => {
    const el = document.createElement('gb-late') as GameBrowserElement
    el.pick = { appIds: pickable, selected: 2, onSelect: vi.fn() }
    define('gb-late', class extends GameBrowser {})
    document.body.append(el)
    await screen.findByText('5 of 5 games')
    expect(el).toBeInstanceOf(GameBrowser)
    expect(Object.hasOwn(el, 'pick')).toBe(false)
    expect(card('The Witcher 2')).toHaveAttribute('aria-pressed', 'true')
  })
})
