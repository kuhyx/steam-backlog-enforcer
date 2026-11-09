import { screen, waitFor } from '@testing-library/dom'
import { q } from '../api/queries'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeLibGame } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import './gameBrowser'

// The grid trails the search box by one animation frame (as useDeferredValue
// did). Hold frames to keep the lag open, then release them deterministically.
function holdFrames() {
  const held: FrameRequestCallback[] = []
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => held.push(cb))
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  return () => {
    for (const cb of held.splice(0)) cb(performance.now())
  }
}
const grid = () => screen.getByRole('group', { name: 'Games' })
const loaded = () =>
  waitFor(() => {
    expect(q.library.state.data).toBeDefined()
  })
const titles = () => [...grid().querySelectorAll('.game-title')].map((t) => t.textContent)

describe('GameBrowser while the grid lags the search box', () => {
  it('focuses a suggested card once the grid shows it', async () => {
    stubApi({
      'GET /api/library': {
        games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' }), makeLibGame({ app_id: 2, name: 'The Witcher' })],
      },
    })
    const release = holdFrames()
    mount('<game-browser></game-browser>')
    const box = await screen.findByRole('combobox', { name: 'Search your games' })
    await loaded()
    await userEvent.type(box, 'hollow')
    release()
    expect(titles()).toEqual(['Hollow Knight'])
    await userEvent.clear(box)
    await userEvent.type(box, 'witcher')
    await userEvent.keyboard('{Enter}')
    // The grid still shows only "Hollow Knight": nothing to focus yet.
    expect(titles()).toEqual(['Hollow Knight'])
    expect(box).toHaveFocus()
    release()
    expect(titles()).toEqual(['The Witcher'])
    expect(screen.getByRole('button', { name: /The Witcher/ })).toHaveFocus()
  })

  it('coalesces a burst of keystrokes into one grid update', async () => {
    stubApi({ 'GET /api/library': { games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' })] } })
    const release = holdFrames()
    mount('<game-browser></game-browser>')
    const box = await screen.findByRole('combobox', { name: 'Search your games' })
    await loaded()
    release()
    const raf = vi.mocked(requestAnimationFrame)
    const calls = vi.fn(raf)
    vi.stubGlobal('requestAnimationFrame', calls)
    await userEvent.type(box, 'hollow')
    expect(calls).toHaveBeenCalledTimes(1)
  })

  it('filters a 3000-game library in the next frame', async () => {
    const games = Array.from({ length: 3000 }, (_, i) => makeLibGame({ app_id: i + 1, name: `Game number ${i} of the backlog` }))
    stubApi({ 'GET /api/library': { games } })
    const release = holdFrames()
    mount('<game-browser></game-browser>')
    const box = await screen.findByRole('combobox', { name: 'Search your games' })
    await loaded()
    release() // first paint builds the cards
    ;(box as HTMLInputElement).value = 'number 12'
    box.dispatchEvent(new Event('input', { bubbles: true }))
    release()
    // Wall-clock budgets are measured in real Chromium (live check), not in
    // jsdom under a 10 % CPU cap where they only measure the scheduler.
    expect(titles().length).toBeGreaterThan(0)
    expect(titles()[0]).toBe('Game number 12 of the backlog')
  })
})
