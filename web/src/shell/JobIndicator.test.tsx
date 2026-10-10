import { act, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob } from '../test/fixtures'
import { FakeEventSource, installEventSource, renderRouted, stubApi } from '../test/harness'
import { JobIndicator } from './JobIndicator'

describe('JobIndicator', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('renders nothing while no job is active', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'a', state: 'succeeded' })] })
    renderRouted(<JobIndicator />)
    await act(async () => {})
    expect(screen.queryByLabelText('Running jobs')).toBeNull()
  })

  it('renders nothing before the list loads', () => {
    stubApi({ 'GET /api/jobs': () => new Promise(() => {}) })
    renderRouted(<JobIndicator />)
    expect(screen.queryByLabelText('Running jobs')).toBeNull()
  })

  it('shows at most two running jobs as links with their progress', async () => {
    stubApi({
      'GET /api/jobs': [
        makeJob({ id: 'a', command: 'scan', progress: { step: 2, total: 8, label: 'Scanning' } }),
        makeJob({ id: 'b', command: 'check', progress: { step: 1, total: null, label: 'Checking' } }),
        makeJob({ id: 'c', command: 'done' }),
      ],
    })
    renderRouted(<JobIndicator />)
    const chips = await screen.findAllByRole('link')
    expect(chips).toHaveLength(2)
    expect(chips[0]).toHaveAccessibleName('Scan: Scanning')
    expect(chips[0]).toHaveTextContent('2/8')
    expect(chips[0]).toHaveAttribute('href', '/jobs/a')
    expect(chips[1]).toHaveTextContent('…')
  })

  it('says "running" for a job with no progress yet', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'a', command: 'scan' })] })
    renderRouted(<JobIndicator />)
    expect(await screen.findByRole('link')).toHaveAccessibleName('Scan: running')
  })

  it('follows live events and flags a job that needs input', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'live-chip', command: 'scan' })] })
    renderRouted(<JobIndicator />)
    await screen.findByRole('link')
    act(() => {
      FakeEventSource.last.emit('progress', { seq: 1, ts: 't', type: 'progress', step: 3, total: 6, label: 'Halfway' })
    })
    expect(screen.getByRole('link')).toHaveTextContent('3/6')
    act(() => {
      FakeEventSource.last.emit('state', { seq: 2, ts: 't', type: 'state', state: 'waiting_input' })
    })
    expect(screen.getByRole('link')).toHaveAccessibleName('Scan: needs your input')
    expect(screen.getByRole('link')).toHaveClass('jobchip-wait')
    expect(screen.getByRole('link')).toHaveTextContent('needs input')
  })
})
