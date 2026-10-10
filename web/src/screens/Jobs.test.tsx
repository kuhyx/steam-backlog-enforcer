import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makeSpec } from '../test/fixtures'
import { apiError, installEventSource, renderRouted, stubApi } from '../test/harness'
import { JobDetail, Jobs } from './Jobs'

describe('Jobs', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('lists jobs with command, params, state, duration and summary', async () => {
    stubApi({
      'GET /api/jobs': [
        makeJob({ id: 'a', command: 'pick-manual', params: { app_id: 5, note: 'x' }, state: 'succeeded', started_at: '2026-10-10T10:00:00Z', ended_at: '2026-10-10T10:01:05Z', summary: 'Picked 5' }),
        makeJob({ id: 'b', command: 'scan', progress: { step: 1, total: 2, label: 'Scanning' } }),
        makeJob({ id: 'c', command: 'done' }),
      ],
    })
    renderRouted(<Jobs />)
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pick manual' })).toHaveAttribute('href', '/jobs/a')
    expect(screen.getByText('app_id=5 note=x')).toBeInTheDocument()
    expect(screen.getByText('1:05')).toBeInTheDocument()
    expect(screen.getByText('Picked 5')).toBeInTheDocument()
    expect(screen.getByText('Scanning')).toBeInTheDocument()
    expect(screen.getAllByText('Running')).toHaveLength(2)
  })

  it('shows loading, then an invitation when there are no jobs', async () => {
    let answer: (v: unknown) => void = () => {}
    stubApi({ 'GET /api/jobs': () => new Promise((r) => (answer = r)) })
    renderRouted(<Jobs />)
    expect(await screen.findByText(/Loading jobs/)).toBeInTheDocument()
    answer([])
    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/jobs': apiError(500, 'op_failed', 'jobs broke') })
    renderRouted(<Jobs />)
    expect(await screen.findByText('jobs broke')).toBeInTheDocument()
    expect(screen.queryByText(/Loading jobs/)).toBeNull()
  })
})

describe('JobDetail', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('shows the job with its live progress', async () => {
    stubApi({
      'GET /api/jobs/jd-1': makeJob({ id: 'jd-1', command: 'scan', created_at: '2026-10-10T10:00:00Z' }),
      'GET /api/commands': [makeSpec('scan')],
    })
    renderRouted(<JobDetail jobId="jd-1" />)
    expect(await screen.findByRole('heading', { name: 'Scan', level: 1 })).toBeInTheDocument()
    expect(screen.getByText(/created/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Job Scan' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'All jobs' }))
  })

  it('titles itself generically until the job loads, and shows an error', async () => {
    stubApi({ 'GET /api/jobs/jd-2': apiError(404, 'not_found', 'no such job'), 'GET /api/commands': [] })
    renderRouted(<JobDetail jobId="jd-2" />)
    expect(await screen.findByRole('heading', { name: 'Job', level: 1 })).toBeInTheDocument()
    expect(await screen.findByText('no such job')).toBeInTheDocument()
    expect(screen.getByText('jd-2')).toBeInTheDocument()
  })
})
