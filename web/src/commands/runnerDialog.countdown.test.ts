import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makePending, makeSpec } from '../test/fixtures'
import { button, setValue, submit } from '../test/events'
import { apiError, bodiesOf, flush } from '../test/harness'
import { found, openRunner, phraseInput, text } from '../test/runnerHelpers'

const SPEC = makeSpec('gaming-reset', {
  privileged: true,
  friction: { phrase_template: 'reset gaming now', countdown_seconds: 300 },
})
const READY = makePending({ ready_at: '2026-10-10T09:00:00Z', armed_at: '2026-10-10T08:55:00Z' })
const FAR = makePending({ ready_at: '2099-01-01T00:00:00Z', armed_at: '2026-10-10T08:55:00Z' })
const DELETE = 'DELETE /api/pending/p1'

function open(extra: Record<string, unknown>) {
  return openRunner([SPEC], 'gaming-reset', { extra })
}
const arm = async () => {
  await vi.waitFor(() => { expect(phraseInput()).toBeInTheDocument() })
  setValue(phraseInput(), 'reset gaming now')
  submit(await found('Arm countdown'))
}
const waitDeletes = (mock: ReturnType<typeof open>['mock'], n: number) =>
  vi.waitFor(() => { expect(bodiesOf(mock, DELETE)).toHaveLength(n) })

describe('<runner-dialog> countdown commands', () => {
  it('sends the phrase to arm, then commits with a retyped phrase and follows the job', async () => {
    const { mock, el } = open({ 'POST /api/jobs': READY, 'POST /api/pending/p1/commit': makeJob({ id: 'j1', command: 'gaming-reset' }) })
    await arm()
    await found('Commit')
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'gaming-reset', params: {}, confirm_phrase: 'reset gaming now' }])
    setValue(phraseInput(), 'reset gaming now')
    submit(button(document.body, 'Commit'))
    await found('Close (job keeps running)')
    expect(bodiesOf(mock, 'POST /api/pending/p1/commit')).toEqual([{ confirm_phrase: 'reset gaming now' }])
    expect(el.querySelector('job-progress')).toHaveAttribute('job-id', 'j1')
  })

  it('cancelling the countdown closes the dialog and the server drops it', async () => {
    const { mock, el } = open({ 'POST /api/jobs': FAR, [DELETE]: undefined })
    await arm()
    ;(await found('Cancel countdown')).click()
    await waitDeletes(mock, 1)
    await vi.waitFor(() => { expect(el.querySelector('dialog')).not.toHaveAttribute('open') })
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('closing the dialog while armed drops the countdown', async () => {
    const { mock, el } = open({ 'POST /api/jobs': FAR, [DELETE]: undefined })
    await arm()
    await found('Cancel countdown')
    el.querySelector<HTMLButtonElement>('.dialog-close')?.click()
    await waitDeletes(mock, 1)
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
  })

  it('closing while armed swallows a refused drop', async () => {
    const { mock, el } = open({ 'POST /api/jobs': FAR, [DELETE]: apiError(404, 'not_found') })
    await arm()
    await found('Cancel countdown')
    el.querySelector<HTMLButtonElement>('.dialog-close')?.click()
    await waitDeletes(mock, 1)
    await flush()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
  })

  it('leaving the page while armed drops it with a keepalive request, even if refused', async () => {
    const { mock } = open({ 'POST /api/jobs': FAR, [DELETE]: apiError(404, 'not_found') })
    await arm()
    await found('Cancel countdown')
    window.dispatchEvent(new Event('pagehide'))
    // Both the dialog and the countdown listen: one drop each.
    await waitDeletes(mock, 2)
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE', keepalive: true }))
    await flush()
  })

  it('after a commit, closing no longer drops anything', async () => {
    const { mock, el } = open({ 'POST /api/jobs': READY, 'POST /api/pending/p1/commit': makeJob({ id: 'j1' }) })
    await arm()
    await found('Commit')
    setValue(phraseInput(), 'reset gaming now')
    submit(button(document.body, 'Commit'))
    ;(await found('Close (job keeps running)')).click()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
    window.dispatchEvent(new Event('pagehide'))
    expect(bodiesOf(mock, DELETE)).toEqual([])
  })
})

describe('<runner-dialog> lapsed countdown', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('arming again after a lapse returns to an empty form', async () => {
    const lapsing = makePending({ ...FAR, heartbeat_interval_seconds: 0.001 })
    open({ 'POST /api/jobs': lapsing, 'POST /api/pending/p1/heartbeat': apiError(410, 'pending_lapsed', 'missed') })
    await vi.advanceTimersByTimeAsync(50)
    await arm()
    await vi.advanceTimersByTimeAsync(50)
    await vi.advanceTimersByTimeAsync(1000)
    button(document.body, 'Arm again').click()
    await vi.advanceTimersByTimeAsync(50)
    expect(phraseInput()).toHaveValue('')
    expect(button(document.body, 'Arm countdown')).toBeDisabled()
    expect(text()).not.toContain('Arm again')
  })
})
