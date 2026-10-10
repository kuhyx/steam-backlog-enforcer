import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource, installEventSource } from '../test/harness'
import { useLiveJob } from './useLiveJob'

describe('useLiveJob', () => {
  beforeEach(() => {
    installEventSource()
    document.head.innerHTML = ''
  })

  it('is null without a job and opens no stream', () => {
    const { result } = renderHook(() => useLiveJob(null))
    expect(result.current).toBeNull()
    expect(FakeEventSource.all).toHaveLength(0)
  })

  it('follows a job while mounted and re-renders on events', () => {
    const { result, unmount } = renderHook(() => useLiveJob('live-1'))
    expect(result.current?.state).toBeNull()
    act(() => FakeEventSource.last.emit('state', { seq: 1, ts: 't', type: 'state', state: 'running' }))
    expect(result.current?.state).toBe('running')
    unmount()
    expect(FakeEventSource.last.closed).toBe(true)
  })

  it('switches streams when the id changes', () => {
    const { rerender } = renderHook(({ id }) => useLiveJob(id), { initialProps: { id: 'live-2' } })
    const first = FakeEventSource.last
    rerender({ id: 'live-3' })
    expect(first.closed).toBe(true)
    expect(FakeEventSource.last.url).toContain('/live-3/')
    vi.clearAllMocks()
  })
})
