import { fireEvent, screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { makeLibGame } from '../test/fixtures'
import { card, grid, render, search, titles, withLibrary } from '../test/browserHelpers'

describe('GameBrowser grid focus', () => {
  beforeEach(() => {
    withLibrary()
  })

  it('Enter on a suggestion moves focus to its card', async () => {
    render()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'hollow')
    await waitFor(() => {
      expect(titles()).toEqual(['Hollow Knight'])
    })
    await userEvent.keyboard('{Enter}')
    expect(card('Hollow Knight')).toHaveFocus()
    expect(card('Hollow Knight')).toHaveAttribute('tabindex', '0')
  })

  it('a card the grid has not drawn yet is focused once it is', async () => {
    render()
    await screen.findByText('5 of 5 games')
    // Typed and chosen in one go: the grid is a frame behind.
    fireEvent.input(search(), { target: { value: 'hollow' } })
    fireEvent.keyDown(search(), { key: 'Enter' })
    await waitFor(() => {
      expect(document.activeElement).toBe(card('Hollow Knight'))
    })
  })

  it('keeps focus on the same game when the library is refetched', async () => {
    render()
    await screen.findByText('5 of 5 games')
    card('Hollow Knight').focus()
    const old = card('Hollow Knight')
    q.library.invalidate()
    await waitFor(() => {
      expect(card('Hollow Knight')).not.toBe(old)
    })
    expect(card('Hollow Knight')).toHaveFocus()
  })

  describe('keyboard in the grid', () => {
    beforeEach(() => {
      withLibrary(Array.from({ length: 12 }, (_, i) => makeLibGame({ app_id: i + 1, name: `Game ${String(i).padStart(2, '0')}` })))
      // jsdom lays nothing out; only the grid is told it has three columns.
      const real = window.getComputedStyle.bind(window)
      vi.spyOn(window, 'getComputedStyle').mockImplementation((el, pseudo) => {
        const style = real(el, pseudo)
        if (!el.classList.contains('game-grid')) return style
        return new Proxy(style, {
          get: (t, k) => {
            if (k === 'gridTemplateColumns') return '1fr 1fr 1fr'
            const v: unknown = Reflect.get(t, k)
            return typeof v === 'function' ? (v as () => unknown).bind(t) : v
          },
        })
      })
    })
    afterEach(() => {
      vi.restoreAllMocks()
    })

    const press = (key: string) => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key })
    }
    const at = () => (document.activeElement as HTMLElement).querySelector('.game-title')?.textContent

    it('moves by cell, row, page and to the ends (roving tabindex)', async () => {
      render()
      await screen.findByText('12 of 12 games')
      card('Game 00').focus()
      press('ArrowRight')
      expect(at()).toBe('Game 01')
      press('ArrowDown')
      expect(at()).toBe('Game 04')
      press('ArrowLeft')
      expect(at()).toBe('Game 03')
      press('ArrowUp')
      expect(at()).toBe('Game 00')
      press('PageDown')
      expect(at()).toBe('Game 09')
      press('PageUp')
      expect(at()).toBe('Game 00')
      press('End')
      expect(at()).toBe('Game 11')
      expect(card('Game 11')).toHaveAttribute('tabindex', '0')
      expect(card('Game 00')).toHaveAttribute('tabindex', '-1')
      expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1)
      press('Home')
      expect(at()).toBe('Game 00')
      press('ArrowUp') // clamps at the first card
      expect(at()).toBe('Game 00')
    })

    it('leaves other keys alone', async () => {
      render()
      await screen.findByText('12 of 12 games')
      const e = new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true })
      card('Game 00').dispatchEvent(e)
      expect(e.defaultPrevented).toBe(false)
    })

    it('ignores navigation keys when nothing is shown', async () => {
      render()
      await screen.findByText('12 of 12 games')
      await userEvent.type(search(), 'qqqqqq')
      await screen.findByText('No game matches.')
      const e = new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true })
      grid().dispatchEvent(e)
      expect(e.defaultPrevented).toBe(false)
    })

    it('a click makes that card the tab stop', async () => {
      render()
      await screen.findByText('12 of 12 games')
      await userEvent.click(card('Game 05'))
      expect(card('Game 05')).toHaveAttribute('tabindex', '0')
      expect(card('Game 00')).toHaveAttribute('tabindex', '-1')
    })

    it('falls back to one column when the layout is unknown', async () => {
      vi.restoreAllMocks() // jsdom computes no grid columns
      render()
      await screen.findByText('12 of 12 games')
      card('Game 00').focus()
      press('ArrowDown')
      expect(at()).toBe('Game 01')
    })
  })
})
