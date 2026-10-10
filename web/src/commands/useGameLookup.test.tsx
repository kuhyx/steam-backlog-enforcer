import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { makeDataset, makeGame } from '../test/factories'
import { makeInstalled, makeStatus } from '../test/fixtures'
import { stubApi } from '../test/harness'
import { useGameLookup } from './useGameLookup'

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
)

describe('useGameLookup', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is empty until the sources load', () => {
    stubApi({ 'GET /api/dataset': makeDataset([]), 'GET /api/installed': { games: [] }, 'GET /api/status': makeStatus({ current_app_id: null }) })
    const { result } = renderHook(() => useGameLookup(), { wrapper })
    expect(result.current.games).toEqual([])
    expect(result.current.ctx.gameName(1)).toBeNull()
    expect(result.current.ctx.installed).toBeNull()
  })

  it('merges backlog, installed, manual picks and the assignment, sorted by name', async () => {
    stubApi({
      'GET /api/dataset': makeDataset([makeGame({ app_id: 1, name: 'Zeta' }), makeGame({ app_id: 2, name: 'Old name' })]),
      'GET /api/installed': { games: [makeInstalled({ app_id: 2, name: 'Beta' })] },
      'GET /api/status': makeStatus({
        current_app_id: 4,
        current_game_name: 'Delta',
        manual_picks: [{ app_id: 3, name: 'Gamma', age_days: 1 }],
      }),
    })
    const { result } = renderHook(() => useGameLookup(), { wrapper })
    await waitFor(() => expect(result.current.games).toHaveLength(4))
    expect(result.current.games.map((g) => g.name)).toEqual(['Beta', 'Delta', 'Gamma', 'Zeta'])
    expect(result.current.ctx.gameName(2)).toBe('Beta')
    expect(result.current.ctx.installed).toHaveLength(1)
  })

  it('skips an unassigned status', async () => {
    stubApi({
      'GET /api/dataset': makeDataset([makeGame({ app_id: 1, name: 'Zeta' })]),
      'GET /api/installed': { games: [] },
      'GET /api/status': makeStatus({ current_app_id: null, current_game_name: null }),
    })
    const { result } = renderHook(() => useGameLookup(), { wrapper })
    await waitFor(() => expect(result.current.games).toHaveLength(1))
  })
})
