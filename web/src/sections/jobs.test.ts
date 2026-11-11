import { screen, waitFor } from '@testing-library/dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makeSpec } from '../test/fixtures'
import { apiError, FakeEventSource, flush, installEventSource, mount, stubApi } from '../test/harness'
import { jobIdFromUrl } from './jobs'

const at = (url: string) => {
  history.replaceState({}, '', url)
}

describe('jobIdFromUrl', () => {
  it('reads the id, treating a missing or empty one as the list', () => {
    expect(jobIdFromUrl('?id=a%20b')).toBe('a b')
    expect(jobIdFromUrl('?id=')).toBeNull()
    expect(jobIdFromUrl('')).toBeNull()
  })
})

describe('jobs list', () => {
  beforeEach(() => {
    installEventSource()
    at('/jobs/')
  })
  afterEach(() => {
    at('/')
  })

  it('lists jobs with command, params, state, duration and summary', async () => {
    stubApi({
      'GET /api/jobs': [
        makeJob({ id: 'a', command: 'pick-manual', params: { app_id: 5, note: 'x' }, state: 'succeeded', started_at: '2026-10-10T10:00:00Z', ended_at: '2026-10-10T10:01:05Z', summary: 'Picked 5' }),
        makeJob({ id: 'b', command: 'scan', progress: { step: 1, total: 2, label: 'Scanning' } }),
        makeJob({ id: 'c', command: 'done' }),
      ],
    })
    mount('<jobs-page></jobs-page>')
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Jobs', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Pick manual' })).toHaveAttribute('href', '/jobs/?id=a')
    expect(screen.getByText('app_id=5 note=x')).toBeInTheDocument()
    expect(screen.getByText('1:05')).toBeInTheDocument()
    expect(screen.getByText('Picked 5')).toBeInTheDocument()
    expect(screen.getByText('Scanning')).toBeInTheDocument()
    expect(screen.getAllByLabelText('running')).toHaveLength(2)
  })

  it('keeps the table and its links across ticks, updating only durations', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval', 'Date'] })
    vi.setSystemTime(new Date('2026-10-10T10:00:11Z'))
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'a', started_at: '2026-10-10T10:00:01Z' })] })
    mount('<jobs-page></jobs-page>')
    await flush(10)
    const table = screen.getByRole('region', { name: 'Job history' })
    const anchor = screen.getByRole('link', { name: 'Scan' })
    expect(screen.getByText('0:10')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.getByRole('region', { name: 'Job history' })).toBe(table)
    expect(screen.getByRole('link', { name: 'Scan' })).toBe(anchor)
    expect(screen.getByText('0:15')).toBeInTheDocument()
  })

  it('shows loading, then an invitation when there are no jobs', async () => {
    let answer: (v: unknown) => void = () => undefined
    stubApi({ 'GET /api/jobs': () => new Promise((r) => (answer = r)) })
    mount('<jobs-page></jobs-page>')
    expect(await screen.findByText(/Loading jobs/)).toBeInTheDocument()
    answer([])
    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/jobs': apiError(500, 'op_failed', 'jobs broke') })
    mount('<jobs-page></jobs-page>')
    expect(await screen.findByText('jobs broke')).toBeInTheDocument()
    expect(screen.queryByText(/Loading jobs/)).toBeNull()
  })
})

describe('job detail', () => {
  beforeEach(installEventSource)
  afterEach(() => {
    at('/')
  })

  it('shows the job with its live progress and a way back', async () => {
    at('/jobs/?id=jd-1')
    stubApi({
      'GET /api/jobs/jd-1': makeJob({ id: 'jd-1', command: 'scan', created_at: '2026-10-10T10:00:00Z' }),
      'GET /api/commands': [makeSpec('scan')],
    })
    mount('<jobs-page></jobs-page>')
    expect(screen.getByRole('heading', { name: 'Job', level: 1 })).toBeInTheDocument()
    expect(screen.getByText(/Loading job/)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Scan', level: 1 })).toBeInTheDocument()
    expect(screen.getByText(/created/)).toBeInTheDocument()
    expect(screen.getByText('jd-1')).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Job Scan' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All jobs' })).toHaveAttribute('href', '/jobs/')
    expect(screen.queryByText(/Loading job/)).toBeNull()
    expect(document.querySelectorAll('job-progress')).toHaveLength(1)
  })

  it('says a missing job is missing, without a live view', async () => {
    at('/jobs/?id=nope')
    stubApi({ 'GET /api/jobs/nope': apiError(404, 'not_found', 'No job nope.') })
    mount('<jobs-page></jobs-page>')
    expect(await screen.findByRole('heading', { name: 'Job not found', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('No job nope.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'See all jobs' })).toHaveAttribute('href', '/jobs/')
    expect(document.querySelector('job-progress')).toBeNull()
    expect(FakeEventSource.all).toHaveLength(0)
  })

  it('stops polling an unknown job', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval'] })
    at('/jobs/?id=nope')
    const mock = stubApi({ 'GET /api/jobs/nope': apiError(404, 'not_found', 'No job nope.') })
    mount('<jobs-page></jobs-page>')
    await flush(10)
    expect(screen.getByRole('heading', { name: 'Job not found', level: 1 })).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mock.mock.calls.filter(([p]) => p === '/api/jobs/nope')).toHaveLength(1)
  })

  it('omits an empty server message from the not-found notice', async () => {
    at('/jobs/?id=gone')
    stubApi({ 'GET /api/jobs/gone': apiError(404, 'not_found') })
    mount('<jobs-page></jobs-page>')
    const title = await screen.findByText('Job not found', { selector: '.notice-title' })
    expect(title.parentElement?.querySelectorAll('p')).toHaveLength(2)
  })

  it('treats a bare <job-detail> as an unknown job', async () => {
    stubApi({ 'GET /api/jobs/': apiError(404, 'not_found', 'No job.') })
    mount('<job-detail></job-detail>')
    expect(await screen.findByRole('heading', { name: 'Job not found', level: 1 })).toBeInTheDocument()
  })

  it('explains another failure and still offers the live view', async () => {
    at('/jobs/?id=jd-2')
    stubApi({ 'GET /api/jobs/jd-2': apiError(500, 'op_failed', 'job broke'), 'GET /api/commands': [] })
    mount('<jobs-page></jobs-page>')
    expect(await screen.findByText('job broke')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Job', level: 1 })).toBeInTheDocument()
    await waitFor(() => {
      expect(document.querySelector('job-progress')).not.toBeNull()
    })
  })
})
