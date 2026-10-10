import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { makeLibGame } from '../test/fixtures'
import { apiError, stubApi } from '../test/harness'
import { GameBrowser, type PickMode } from './GameBrowser'

const GAMES = [
  makeLibGame({ app_id: 1, name: 'The Witcher', achievements_unlocked: 10, last_played: 100, hltb_hours: 30 }),
  makeLibGame({ app_id: 2, name: 'The Witcher 2', achievements_unlocked: 2, last_played: 300, hltb_hours: 20, installed: true }),
  makeLibGame({ app_id: 3, name: 'The Witcher 3', achievements_unlocked: 5, last_played: null, hltb_hours: null, ineligible_reason: 'Already started' }),
  makeLibGame({ app_id: 4, name: 'Age of Empires III', achievements_unlocked: 5, last_played: 200, hltb_hours: 10 }),
  makeLibGame({ app_id: 5, name: 'Hollow Knight', achievements_unlocked: 1, last_played: 50, hltb_hours: 5 }),
]
const withLibrary = (games = GAMES) => stubApi({ 'GET /api/library': { games } })

function renderBrowser(pick?: PickMode) {
  return render(
    <QueryClientProvider client={queryClient}>
      <GameBrowser pick={pick} />
    </QueryClientProvider>,
  )
}
const titles = () => screen.queryAllByRole('button').filter((b) => b.dataset.appId).map((b) => b.querySelector('.game-title')!.textContent)
const card = (name: string) => screen.getByRole('button', { name: new RegExp(name) })
const search = () => screen.getByRole('combobox', { name: 'Search your games' })

describe('GameBrowser', () => {
  beforeEach(() => {
    withLibrary()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the library sorted by name, with a count', async () => {
    renderBrowser()
    expect(screen.getByText(/Loading your library/)).toBeInTheDocument()
    await screen.findByText('5 of 5 games')
    expect(titles()).toEqual(['Age of Empires III', 'Hollow Knight', 'The Witcher', 'The Witcher 2', 'The Witcher 3'])
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/library': apiError(500, 'op_failed', 'cannot read library') })
    renderBrowser()
    expect(await screen.findByText('cannot read library')).toBeInTheDocument()
    expect(screen.queryByText(/Loading/)).toBeNull()
  })

  it('says so when nothing matches', async () => {
    withLibrary([])
    renderBrowser()
    expect(await screen.findByText('No game matches.')).toBeInTheDocument()
    expect(screen.getByText('0 of 0 games')).toBeInTheDocument()
  })

  it('sorts by the chosen key', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sort' }), 'recent')
    expect(titles()[0]).toBe('The Witcher 2')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sort' }), 'hltb')
    expect(titles()[0]).toBe('Hollow Knight')
  })

  it('filters', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Installed only' }))
    expect(titles()).toEqual(['The Witcher 2'])
    await userEvent.click(screen.getByRole('checkbox', { name: 'Installed only' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Pickable only' }))
    expect(titles()).not.toContain('The Witcher 3')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Hide completed' }))
    expect(titles()).not.toContain('The Witcher')
  })

  it('"wicher" finds the Witcher titles by relevance and locks the sort', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'wicher')
    await screen.findByText(/by relevance/)
    expect(titles()).toEqual(['The Witcher', 'The Witcher 2', 'The Witcher 3'])
    expect(screen.getByRole('combobox', { name: 'Sort' })).toBeDisabled()
  })

  it('"witcher 3" does not return Age of Empires III', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'witcher 3')
    await waitFor(() => expect(titles()[0]).toBe('The Witcher 3'))
    expect(titles()).not.toContain('Age of Empires III')
  })

  it('an app id finds that game', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), '5')
    await waitFor(() => expect(titles()[0]).toBe('Hollow Knight'))
  })

  it('Enter on a suggestion moves focus to its card', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'hollow')
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(card('Hollow Knight')).toHaveFocus())
    expect(card('Hollow Knight')).toHaveAttribute('tabindex', '0')
  })

  it('a missing card is focused once the grid catches up', async () => {
    renderBrowser()
    await screen.findByText('5 of 5 games')
    // Choosing from the list while the grid still shows a stale result.
    await userEvent.type(search(), 'hollow')
    fireEvent.keyDown(search(), { key: 'Enter' })
    await waitFor(() => expect(document.activeElement).toBe(card('Hollow Knight')))
  })

  describe('keyboard in the grid', () => {
    beforeEach(() => {
      withLibrary(Array.from({ length: 12 }, (_, i) => makeLibGame({ app_id: i + 1, name: `Game ${String(i).padStart(2, '0')}` })))
      // jsdom lays nothing out; only the grid is told it has three columns.
      const real = window.getComputedStyle.bind(window)
      vi.spyOn(window, 'getComputedStyle').mockImplementation((el, pseudo) =>
        el.classList.contains('game-grid') ? ({ gridTemplateColumns: '1fr 1fr 1fr' } as CSSStyleDeclaration) : real(el, pseudo),
      )
    })
    afterEach(() => vi.restoreAllMocks())

    const press = async (key: string) => {
      fireEvent.keyDown(document.activeElement!, { key })
      await waitFor(() => expect(document.activeElement).toHaveAttribute('data-app-id'))
    }
    const at = () => (document.activeElement as HTMLElement).querySelector('.game-title')!.textContent

    it('moves by cell, row, page and to the ends (roving tabindex)', async () => {
      renderBrowser()
      await screen.findByText('12 of 12 games')
      card('Game 00').focus()
      await press('ArrowRight')
      await waitFor(() => expect(at()).toBe('Game 01'))
      await press('ArrowDown')
      await waitFor(() => expect(at()).toBe('Game 04'))
      await press('ArrowLeft')
      await waitFor(() => expect(at()).toBe('Game 03'))
      await press('ArrowUp')
      await waitFor(() => expect(at()).toBe('Game 00'))
      await press('PageDown')
      await waitFor(() => expect(at()).toBe('Game 09'))
      await press('PageUp')
      await waitFor(() => expect(at()).toBe('Game 00'))
      await press('End')
      await waitFor(() => expect(at()).toBe('Game 11'))
      expect(card('Game 11')).toHaveAttribute('tabindex', '0')
      expect(card('Game 00')).toHaveAttribute('tabindex', '-1')
      await press('Home')
      await waitFor(() => expect(at()).toBe('Game 00'))
      await press('ArrowUp') // clamps at the first card
      await waitFor(() => expect(at()).toBe('Game 00'))
    })

    it('leaves other keys alone', async () => {
      renderBrowser()
      await screen.findByText('12 of 12 games')
      const e = new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true })
      card('Game 00').dispatchEvent(e)
      expect(e.defaultPrevented).toBe(false)
    })

    it('ignores navigation keys when nothing is shown', async () => {
      renderBrowser()
      await screen.findByText('12 of 12 games')
      await userEvent.type(search(), 'qqqqqq')
      await screen.findByText('No game matches.')
      const e = new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true })
      document.querySelector('.game-grid')!.dispatchEvent(e)
      expect(e.defaultPrevented).toBe(false)
    })

    it('a click makes that card the tab stop', async () => {
      renderBrowser()
      await screen.findByText('12 of 12 games')
      await userEvent.click(card('Game 05'))
      expect(card('Game 05')).toHaveAttribute('tabindex', '0')
    })

    it('falls back to one column when the layout is unknown', async () => {
      vi.restoreAllMocks() // jsdom computes no grid columns
      renderBrowser()
      await screen.findByText('12 of 12 games')
      card('Game 00').focus()
      await press('ArrowDown')
      await waitFor(() => expect(at()).toBe('Game 01'))
    })
  })

  describe('pick mode', () => {
    const pickable = new Set([1, 2])
    const setup = (selected: number | null = null) => {
      const onSelect = vi.fn()
      renderBrowser({ appIds: pickable, selected, onSelect })
      return onSelect
    }

    it('selects eligible cards only, and never submits', async () => {
      const onSelect = setup()
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
    })

    it('"pickable only" keeps just the ids the job sent', async () => {
      setup()
      await screen.findByText('5 of 5 games')
      await userEvent.click(screen.getByRole('checkbox', { name: 'Pickable only' }))
      expect(titles()).toEqual(['The Witcher', 'The Witcher 2'])
    })

    it('choosing a suggestion selects an eligible game but only focuses an ineligible one', async () => {
      const onSelect = setup()
      await screen.findByText('5 of 5 games')
      await userEvent.type(search(), 'hollow')
      await userEvent.keyboard('{Enter}')
      expect(onSelect).not.toHaveBeenCalled()
      await waitFor(() => expect(card('Hollow Knight')).toHaveFocus())
      await userEvent.clear(search())
      await userEvent.type(search(), 'witcher 2')
      await userEvent.keyboard('{Enter}')
      expect(onSelect).toHaveBeenCalledWith(2)
      const grid = screen.getByRole('group', { name: 'Games' })
      await waitFor(() => expect(within(grid).getByRole('button', { name: /The Witcher 2/ })).toHaveFocus())
    })
  })
})
