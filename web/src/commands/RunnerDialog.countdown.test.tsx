import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { routes } from '../test/dialogRoutes'
import { makeJob, makePending, makeSpec } from '../test/fixtures'
import { apiError, bodiesOf, installEventSource, renderRouted, stubApi } from '../test/harness'
import { RunnerDialog } from './RunnerDialog'

const SPEC = makeSpec('gaming-reset', {
  privileged: true,
  friction: { phrase_template: 'reset gaming now', countdown_seconds: 300 },
})
const READY = makePending({ ready_at: '2026-10-10T09:00:00Z', armed_at: '2026-10-10T08:55:00Z' })
const FAR = makePending({ ready_at: '2099-01-01T00:00:00Z', armed_at: '2026-10-10T08:55:00Z' })

function open(extra: Record<string, unknown>) {
  const mock = stubApi(routes([SPEC], extra))
  const onClose = vi.fn()
  const view = renderRouted(<RunnerDialog name="gaming-reset" onClose={onClose} />)
  return { mock, onClose, ...view }
}
const arm = async () => {
  await userEvent.type(await screen.findByLabelText('Type the phrase to confirm'), 'reset gaming now')
  await userEvent.click(screen.getByRole('button', { name: 'Arm countdown' }))
}

describe('RunnerDialog countdown commands', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('sends the phrase to arm, then commits with a retyped phrase and follows the job', async () => {
    const { mock } = open({ 'POST /api/jobs': READY, 'POST /api/pending/p1/commit': makeJob({ id: 'j1', command: 'gaming-reset' }) })
    await arm()
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([
      { command: 'gaming-reset', params: {}, confirm_phrase: 'reset gaming now' },
    ])
    await userEvent.type(await screen.findByLabelText('Retype the phrase to commit'), 'reset gaming now')
    await userEvent.click(screen.getByRole('button', { name: 'Commit' }))
    expect(await screen.findByRole('region', { name: /^Job/ })).toBeInTheDocument()
    expect(bodiesOf(mock, 'POST /api/pending/p1/commit')).toEqual([{ confirm_phrase: 'reset gaming now' }])
  })

  it('cancelling the countdown closes the dialog and the server drops it', async () => {
    const { mock, onClose } = open({ 'POST /api/jobs': FAR, 'DELETE /api/pending/p1': undefined })
    await arm()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel countdown' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('closing the dialog while armed drops the countdown', async () => {
    const { mock, onClose } = open({ 'POST /api/jobs': FAR, 'DELETE /api/pending/p1': undefined })
    await arm()
    await userEvent.click(await screen.findByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('navigating away while armed drops it too, even if the server refuses', async () => {
    const { mock, onClose, router } = open({ 'POST /api/jobs': FAR, 'DELETE /api/pending/p1': apiError(404, 'not_found') })
    await arm()
    await screen.findByRole('button', { name: 'Cancel countdown' })
    await router.navigate({ to: '/jobs' })
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(mock).toHaveBeenCalledWith('/api/pending/p1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('after a commit, closing no longer drops anything', async () => {
    const { mock, onClose } = open({ 'POST /api/jobs': READY, 'POST /api/pending/p1/commit': makeJob({ id: 'j1' }) })
    await arm()
    await userEvent.type(await screen.findByLabelText('Retype the phrase to commit'), 'reset gaming now')
    await userEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Close (job keeps running)' }))
    expect(onClose).toHaveBeenCalled()
    expect(bodiesOf(mock, 'DELETE /api/pending/p1')).toEqual([])
  })

  it('arming again after a lapse returns to an empty form', async () => {
    const lapsing = makePending({ ...FAR, heartbeat_interval_seconds: 0.001 })
    open({ 'POST /api/jobs': lapsing, 'POST /api/pending/p1/heartbeat': apiError(410, 'pending_lapsed', 'missed') })
    await arm()
    await userEvent.click(await screen.findByRole('button', { name: 'Arm again' }, { timeout: 3000 }))
    expect(await screen.findByLabelText('Type the phrase to confirm')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Arm countdown' })).toBeDisabled()
  })
})
