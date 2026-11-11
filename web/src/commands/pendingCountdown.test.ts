import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makePending } from '../test/fixtures'
import { apiError, bodiesOf, flush, stubApi, type Handler } from '../test/harness'
import { button, must, setValue, submit } from '../test/events'
import { PendingCountdown } from './pendingCountdown'

const T0 = Date.parse('2026-10-10T10:00:00Z')
const pending = (over = {}) =>
  makePending({ armed_at: '2026-10-10T10:00:00Z', ready_at: '2026-10-10T10:00:30Z', heartbeat_interval_seconds: 10, ...over })

const made: PendingCountdown[] = []

function make(over = {}) {
  const cbs = { onCommitted: vi.fn(), onCancel: vi.fn(), onRearm: vi.fn() }
  const countdown = new PendingCountdown(pending(over), cbs)
  made.push(countdown)
  document.body.append(countdown.el)
  return { ...cbs, countdown, el: countdown.el }
}
const tick = (ms: number) => vi.advanceTimersByTimeAsync(ms)
const text = () => document.body.textContent
const phraseInput = () => must(document.querySelector<HTMLInputElement>('.phrase input'))

describe('PendingCountdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: T0 })
  })
  afterEach(() => {
    // The pagehide listener lives on window: release every instance.
    for (const c of made.splice(0)) c.dispose()
  })

  it('counts down on the server clock, one second past ready_at', async () => {
    stubApi({ 'POST /api/pending/p1/heartbeat': pending() })
    const { el } = make()
    expect(text()).toContain('0:31')
    expect(text()).toContain('until commit unlocks')
    await tick(10_000)
    expect(text()).toContain('0:21')
    expect(el.querySelector('[role=progressbar]')).toHaveAttribute('aria-valuenow', '32')
    expect(el.querySelector('.notice-warning')).toHaveAttribute(
      'aria-label',
      'Closing this dialog, navigating away or closing the tab cancels the countdown.',
    )
    expect(button(el, 'Cancel countdown')).toHaveAttribute('autofocus')
  })

  it('keeps the commit locked until a second after the ready time', async () => {
    stubApi({ 'POST /api/pending/p1/heartbeat': pending() })
    make()
    await tick(30_000)
    expect(text()).toContain('until commit unlocks')
    await tick(1_000)
    expect(text()).toContain('Ready to commit')
  })

  it('heartbeats at half the interval and takes the server ready time', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': () => pending({ ready_at: '2026-10-10T10:01:00Z' }) })
    make()
    await tick(4_999)
    expect(mock).not.toHaveBeenCalled()
    await tick(1)
    expect(mock).toHaveBeenCalledTimes(1)
    await tick(250)
    expect(text()).toMatch(/Heartbeat every 5 s · last 0 s ago/)
    expect(text()).toContain('0:56')
  })

  it('never heartbeats faster than once a second', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': pending({ heartbeat_interval_seconds: 0.5 }) })
    make({ heartbeat_interval_seconds: 0.5 })
    await tick(999)
    expect(mock).not.toHaveBeenCalled()
    await tick(1)
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('reports a failing heartbeat and recovers when it works again', async () => {
    const routes: Record<string, Handler> = { 'POST /api/pending/p1/heartbeat': apiError(503, 'daemon_unreachable') }
    stubApi(routes)
    make()
    await tick(5_000)
    expect(text()).toContain('heartbeat failing, retrying')
    routes['POST /api/pending/p1/heartbeat'] = pending()
    await tick(5_000)
    expect(text()).not.toContain('heartbeat failing')
  })

  it('offers to arm again once the server says the countdown lapsed', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': apiError(410, 'pending_lapsed', 'missed a beat') })
    const { onRearm, el } = make()
    await tick(5_000)
    expect(text()).toContain('missed a beat')
    expect(el.className).toBe('stack')
    button(el, 'Arm again').click()
    expect(onRearm).toHaveBeenCalled()
    await tick(60_000)
    expect(mock).toHaveBeenCalledTimes(1)
  })

  it('drops the action with a keepalive request when the page is hidden', () => {
    const mock = stubApi({ 'DELETE /api/pending/p1': undefined })
    make()
    window.dispatchEvent(new Event('pagehide'))
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE', keepalive: true }))
  })

  it('swallows a failed keepalive drop', async () => {
    stubApi({ 'DELETE /api/pending/p1': apiError(500, 'op_failed') })
    make()
    window.dispatchEvent(new Event('pagehide'))
    await tick(0)
    expect(text()).toContain('0:31')
  })

  it('stops heartbeating and listening once disposed', async () => {
    const mock = stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'DELETE /api/pending/p1': undefined })
    const { countdown } = make()
    countdown.dispose()
    await tick(60_000)
    window.dispatchEvent(new Event('pagehide'))
    expect(mock).not.toHaveBeenCalled()
  })

  it('cancels, whatever the server answers', async () => {
    stubApi({ 'DELETE /api/pending/p1': apiError(404, 'not_found') })
    const { onCancel, el } = make()
    button(el, 'Cancel countdown').click()
    await tick(0)
    expect(onCancel).toHaveBeenCalled()
  })

  it('shows Cancelling… while the request runs', async () => {
    stubApi({ 'DELETE /api/pending/p1': () => new Promise(() => undefined) })
    const { el, onCancel } = make()
    button(el, 'Cancel countdown').click()
    await flush()
    expect(button(el, 'Cancelling…')).toBeInTheDocument()
    expect(onCancel).not.toHaveBeenCalled()
  })

  describe('once ready', () => {
    const ready = async () => {
      const m = make()
      await tick(31_000)
      return m
    }

    it('asks for the phrase again, and commits only when it matches', async () => {
      const job = makeJob({ id: 'jc' })
      const mock = stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'POST /api/pending/p1/commit': job })
      const { onCommitted, el } = await ready()
      expect(text()).toContain('Ready to commit')
      expect(el.querySelector('.sr-only[aria-live]')).toHaveTextContent('Countdown finished')
      const commit = button(el, 'Commit')
      expect(commit).toBeDisabled()
      submit(commit)
      await flush()
      expect(onCommitted).not.toHaveBeenCalled()
      setValue(phraseInput(), 'reset gaming now')
      expect(commit).toBeEnabled()
      submit(commit)
      await tick(0)
      expect(onCommitted).toHaveBeenCalledWith(job)
      expect(bodiesOf(mock, 'POST /api/pending/p1/commit')).toEqual([{ confirm_phrase: 'reset gaming now' }])
    })

    it('keeps the same input while typing', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending() })
      await ready()
      const input = phraseInput()
      setValue(input, 'res')
      await tick(250)
      expect(phraseInput()).toBe(input)
      expect(input).toHaveValue('res')
    })

    it('shows a refused commit and stays open', async () => {
      stubApi({
        'POST /api/pending/p1/heartbeat': pending(),
        'POST /api/pending/p1/commit': apiError(409, 'countdown_running', 'not yet'),
      })
      const { el, onCommitted } = await ready()
      setValue(phraseInput(), 'reset gaming now')
      submit(button(el, 'Commit'))
      await tick(0)
      expect(text()).toContain('not yet')
      expect(onCommitted).not.toHaveBeenCalled()
    })

    it('shows Committing… while it is in flight', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'POST /api/pending/p1/commit': () => new Promise(() => undefined) })
      const { el } = await ready()
      setValue(phraseInput(), 'reset gaming now')
      submit(button(el, 'Commit'))
      await flush()
      expect(button(el, 'Committing…')).toBeDisabled()
    })

    it('can still be cancelled', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'DELETE /api/pending/p1': undefined })
      const { el, onCancel } = await ready()
      button(el, 'Cancel').click()
      await tick(0)
      expect(onCancel).toHaveBeenCalled()
    })

    it('can be cancelled in flight and keeps the phrase form', async () => {
      stubApi({ 'POST /api/pending/p1/heartbeat': pending(), 'DELETE /api/pending/p1': () => new Promise(() => undefined) })
      const { el } = await ready()
      button(el, 'Cancel').click()
      await flush()
      expect(phraseInput()).toBeInTheDocument()
    })
  })
})
