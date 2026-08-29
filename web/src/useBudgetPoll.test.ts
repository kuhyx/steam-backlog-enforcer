import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBudget } from './test/factories'
import { useBudgetPoll } from './useBudgetPoll'

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
}

describe('useBudgetPoll', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setHidden(false)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    // defineProperty is not undone by unstubAllGlobals.
    setHidden(false)
  })

  it('loads a snapshot on mount', async () => {
    const snapshot = makeBudget()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot }),
    )
    const { result } = renderHook(() => useBudgetPoll(false))
    await waitFor(() => expect(result.current.data).not.toBeNull())
    expect(result.current.error).toBeNull()
    expect(result.current.data?.today?.gaming_day).toBe('2026-08-28')
  })

  it('requests the demo run when asked', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => makeBudget() })
    vi.stubGlobal('fetch', fetchMock)
    renderHook(() => useBudgetPoll(true))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/budget?demo=1'))
  })

  it('reports a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'Server Error' }),
    )
    const { result } = renderHook(() => useBudgetPoll(false))
    await waitFor(() => expect(result.current.error).toMatch(/500/))
  })

  it('handles a non-Error rejection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('network down'))
    const { result } = renderHook(() => useBudgetPoll(false))
    await waitFor(() => expect(result.current.error).toBe('network down'))
  })

  it('polls again on the interval', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => makeBudget() })
    vi.stubGlobal('fetch', fetchMock)
    renderHook(() => useBudgetPoll(false, 1000))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => {
      vi.advanceTimersByTime(2000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('does not poll while the tab is hidden', async () => {
    vi.useFakeTimers()
    setHidden(true)
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => makeBudget() })
    vi.stubGlobal('fetch', fetchMock)
    renderHook(() => useBudgetPoll(false, 1000))
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('stops polling after unmount', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => makeBudget() })
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = renderHook(() => useBudgetPoll(false, 1000))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    unmount()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('drops a response that arrives after unmount', async () => {
    let resolve: (value: unknown) => void = () => {}
    const pending = new Promise((r) => {
      resolve = r
    })
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending))
    const { unmount, result } = renderHook(() => useBudgetPoll(false))
    unmount()
    await act(async () => {
      resolve({ ok: true, json: async () => makeBudget() })
      await pending
    })
    expect(result.current.data).toBeNull()
  })

  it('drops a rejection that arrives after unmount', async () => {
    let reject: (reason: unknown) => void = () => {}
    const pending = new Promise((_r, rj) => {
      reject = rj
    })
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(pending))
    const { unmount, result } = renderHook(() => useBudgetPoll(false))
    unmount()
    await act(async () => {
      reject(new Error('too late'))
      await pending.catch(() => undefined)
    })
    expect(result.current.error).toBeNull()
  })
})
