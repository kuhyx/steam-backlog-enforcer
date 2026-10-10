import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { stubApi } from '../test/harness'
import { useServerRestart } from './useServerRestart'

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
)

describe('useServerRestart', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reloads when the first answer arrives after a restart asked before any answer', async () => {
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload })
    let answer: (v: unknown) => void = () => {}
    stubApi({
      'GET /api/server': () => new Promise((r) => (answer = r)),
      'POST /api/server/restart': undefined,
    })
    const { result } = renderHook(() => useServerRestart(), { wrapper })
    expect(result.current.restarting).toBe(false)
    await act(async () => {
      result.current.restart.mutate()
    })
    await waitFor(() => expect(result.current.restarting).toBe(true))
    expect(reload).not.toHaveBeenCalled()
    await act(async () => answer({ stale: false, started_at: '2026-10-10T12:00:00Z', version: '1' }))
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
  })
})
