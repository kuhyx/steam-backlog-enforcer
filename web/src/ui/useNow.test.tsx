import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNow } from './useNow'

describe('useNow', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(1_000_000)
  })
  afterEach(() => vi.useRealTimers())

  it('ticks at the requested rate and stops on unmount', () => {
    const { result, unmount } = renderHook(() => useNow(500))
    expect(result.current).toBe(1_000_000)
    act(() => vi.advanceTimersByTime(500))
    expect(result.current).toBe(1_000_500)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('defaults to one second', () => {
    const { result } = renderHook(() => useNow())
    act(() => vi.advanceTimersByTime(1000))
    expect(result.current).toBe(1_001_000)
  })
})
