import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { makeJob, makePending } from '../test/fixtures'
import { apiError, stubApi } from '../test/harness'
import { PendingCountdown } from './PendingCountdown'

const T0 = Date.parse('2026-10-10T10:00:00Z')
const pending = (over = {}) =>
  makePending({ armed_at: '2026-10-10T10:00:00Z', ready_at: '2026-10-10T10:00:30Z', heartbeat_interval_seconds: 10, ...over })

function mount(over = {}) {
  const cbs = { onCommitted: vi.fn(), onCancel: vi.fn(), onRearm: vi.fn() }
  const p = pending(over)
  const view = render(
    <QueryClientProvider client={queryClient}>
      <PendingCountdown pending={p} {...cbs} />
    </QueryClientProvider>,
  )
  return { ...cbs, ...view }
}
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })
const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

describe('PendingCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: T0 })
    // Testing Library only advances fake timers for a `jest` global; without
    // this shim its async helpers wait on a timer that never fires.
    vi.stubGlobal('jest', { advanceTimersByTime: vi.advanceTimersByTime })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('counts down on the server’s clock', async () => {
    stubApi({ 'POST /api/pending/p1/heartbeat': pending() })
    mount()
    expect(screen.getByText('0:30')).toBeInTheDocument()
    expect(screen.getByText('until commit unlocks')).toBeInTheDocument()
    await tick(10_000)
    expect(screen.getByText('0:20')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Countdown' })).toHaveAttribute('aria-valuenow', '33')
    expect(screen.getByText(/Closing this dialog/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel countdown' })).toHaveFocus()
  })

  it('heartbeats at half the interval, and takes the server’s new ready time', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': () => pending({ ready_at: '2026-10-10T10:01:00Z' }) })
    mount()
    await tick(4_999)
    expect(mock).not.toHaveBeenCalled()
    await tick(1)
    expect(mock).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/Heartbeat every 5 s · last 0 s ago/)).toBeInTheDocument()
    expect(screen.getByText('0:55')).toBeInTheDocument() // pushed out by the server
  })

  it('never heartbeats faster than once a second', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': pending({ heartbeat_interval_seconds: 0.5 }) })
    mount({ heartbeat_interval_seconds: 0.5 })
    await tick(999)
    expect(mock).not.toHaveBeenCalled()
    await tick(1)
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('reports a failing heartbeat and recovers when it works again', async () => {
    const routes: Record<string, unknown> = { 'POST /api/pending/p1/heartbeat': apiError(503, 'daemon_unreachable') }
    stubApi(routes)
    mount()
    await tick(5_000)
    expect(screen.getByText(/heartbeat failing, retrying/)).toBeInTheDocument()
    routes['POST /api/pending/p1/heartbeat'] = pending()
    await tick(5_000)
    expect(screen.queryByText(/heartbeat failing/)).toBeNull()
  })

  it('offers to arm again once the server says the countdown lapsed', async () => {
    stubApi({ 'POST /api/pending/p1/heartbeat': apiError(410, 'pending_lapsed', 'missed a beat') })
    const { onRearm } = mount()
    await tick(5_000)
    expect(screen.getByText('missed a beat')).toBeInTheDocument()
    await user().click(screen.getByRole('button', { name: 'Arm again' }))
    expect(onRearm).toHaveBeenCalled()
  })

  it('drops the action with a keepalive request when the page is hidden', async () => {
    const mock = stubApi({ 'DELETE /api/pending/p1': undefined })
    mount()
    window.dispatchEvent(new Event('pagehide'))
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE', keepalive: true }))
  })

  it('swallows a failed keepalive drop', async () => {
    stubApi({ 'DELETE /api/pending/p1': apiError(500, 'op_failed') })
    mount()
    window.dispatchEvent(new Event('pagehide'))
    await tick(0)
    expect(screen.getByText('0:30')).toBeInTheDocument()
  })

  it('stops heartbeating and listening on unmount', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'DELETE /api/pending/p1': undefined })
    const { unmount } = mount()
    unmount()
    await tick(60_000)
    window.dispatchEvent(new Event('pagehide'))
    expect(mock).not.toHaveBeenCalled()
  })

  it('cancels, whatever the server answers', async () => {
    stubApi({ 'DELETE /api/pending/p1': apiError(404, 'not_found') })
    const { onCancel } = mount()
    await user().click(screen.getByRole('button', { name: 'Cancel countdown' }))
    await tick(0)
    expect(onCancel).toHaveBeenCalled()
  })

  it('shows Cancelling… while the request runs', async () => {
    stubApi({ 'DELETE /api/pending/p1': () => new Promise(() => {}) })
    mount()
    await user().click(screen.getByRole('button', { name: 'Cancel countdown' }))
    expect(screen.getByRole('button', { name: 'Cancelling…' })).toBeInTheDocument()
  })

  describe('once ready', () => {
    const ready = async (over = {}) => {
      const m = mount(over)
      await tick(31_000)
      return m
    }

    it('asks for the phrase again, and commits only when it matches', async () => {
      const job = makeJob({ id: 'jc' })
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'POST /api/pending/p1/commit': job })
      const { onCommitted } = await ready()
      expect(screen.getByText('Ready to commit')).toBeInTheDocument()
      expect(screen.getByRole('textbox')).toHaveFocus()
      const commit = screen.getByRole('button', { name: 'Commit' })
      expect(commit).toBeDisabled()
      fireEvent.submit(commit.closest('form')!) // Enter with the wrong phrase
      expect(onCommitted).not.toHaveBeenCalled()
      await user().type(screen.getByRole('textbox'), 'reset gaming now')
      expect(commit).toBeEnabled()
      await user().click(commit)
      await tick(0)
      expect(onCommitted.mock.calls[0][0]).toEqual(job)
    })

    it('shows a refused commit', async () => {
      stubApi({
        'POST /api/pending/p1/heartbeat': pending(),
        'POST /api/pending/p1/commit': apiError(409, 'countdown_running', 'not yet'),
      })
      await ready()
      await user().type(screen.getByRole('textbox'), 'reset gaming now')
      await user().click(screen.getByRole('button', { name: 'Commit' }))
      await tick(0)
      expect(screen.getByText('not yet')).toBeInTheDocument()
    })

    it('shows Committing… while it is in flight', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'POST /api/pending/p1/commit': () => new Promise(() => {}) })
      await ready()
      await user().type(screen.getByRole('textbox'), 'reset gaming now')
      await user().click(screen.getByRole('button', { name: 'Commit' }))
      expect(screen.getByRole('button', { name: 'Committing…' })).toBeDisabled()
    })

    it('can still be cancelled', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'DELETE /api/pending/p1': undefined })
      const { onCancel } = await ready()
      await user().click(screen.getByRole('button', { name: 'Cancel' }))
      await tick(0)
      expect(onCancel).toHaveBeenCalled()
    })
  })
})
