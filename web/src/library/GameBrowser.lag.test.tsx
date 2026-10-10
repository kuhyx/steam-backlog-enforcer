import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { makeLibGame } from '../test/fixtures'
import { stubApi } from '../test/harness'
import { GameBrowser } from './GameBrowser'

// The grid trails the search box by design (useDeferredValue). Pin the
// trailing value so the lag can be held open and released deterministically.
const lag = vi.hoisted(() => ({ value: undefined as string | undefined }))
vi.mock('react', async (importOriginal) => {
  const real = await importOriginal<typeof import('react')>()
  return { ...real, useDeferredValue: <T,>(v: T): T => (lag.value ?? v) as T }
})

describe('GameBrowser while the grid lags the search box', () => {
  it('focuses a suggested card once the grid shows it', async () => {
    stubApi({
      'GET /api/library': {
        games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' }), makeLibGame({ app_id: 2, name: 'The Witcher' })],
      },
    })
    lag.value = 'hollow'
    render(
      <QueryClientProvider client={queryClient}>
        <GameBrowser />
      </QueryClientProvider>,
    )
    const box = await screen.findByRole('combobox', { name: 'Search your games' })
    await userEvent.type(box, 'witcher')
    await userEvent.keyboard('{Enter}')
    // The grid still shows only "Hollow Knight": nothing to focus yet.
    expect(screen.queryByRole('button', { name: /The Witcher/ })).toBeNull()
    lag.value = undefined
    await userEvent.type(box, ' ')
    await waitFor(() => expect(screen.getByRole('button', { name: /The Witcher/ })).toHaveFocus())
  })
})
