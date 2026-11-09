import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError, installEventSource } from '../test/harness'
import { button } from '../test/events'
import { mountJob } from '../test/jobHelpers'
import type { LiveJob } from './hub'
import { eta } from './jobProgress'

beforeEach(installEventSource)

const text = (el: Element) => el.textContent
const sel = (el: Element, s: string) => el.querySelector(s)

describe('eta', () => {
  const live = (startedProgressAt: number | null) => ({ startedProgressAt }) as LiveJob
  it('prefers the job estimate, then extrapolates from the pace', () => {
    expect(eta({ step: 1, total: 5, label: 'x', eta_seconds: 9 }, live(null), 0)).toBe(9)
    expect(eta({ step: 2, total: 5, label: 'x' }, live(0), 10_000)).toBe(15)
  })
  it('has no estimate without a total, a first step or a start time', () => {
    expect(eta({ step: 2, total: null, label: 'x' }, live(0), 1000)).toBeNull()
    expect(eta({ step: 0, total: 5, label: 'x' }, live(0), 1000)).toBeNull()
    expect(eta({ step: 2, total: 5, label: 'x' }, live(null), 1000)).toBeNull()
    expect(eta({ step: 2, total: 5, label: 'x', eta_seconds: undefined }, live(null), 1000)).toBeNull()
  })
})

describe('<job-progress>', () => {
  it('starts from the fetched job and shows "Starting…" before any progress', async () => {
    const { el } = mountJob({ job: { state: 'running' } })
    expect(text(el)).toContain('Starting…')
    expect(text(el)).toContain('Queued')
    expect(sel(el, 'h3')).toHaveTextContent('Job')
    await vi.waitFor(() => { expect(text(el)).toContain('Running') })
    expect(sel(el, 'h3')).toHaveTextContent('Scan')
    expect(sel(el, '[role=progressbar]')).not.toHaveAttribute('aria-valuenow')
    expect(sel(el, 'section')).toHaveAttribute('aria-label', 'Job Scan')
  })

  it('names the section after the id until the job loads', () => {
    const { el, id } = mountJob()
    expect(sel(el, 'section')).toHaveAttribute('aria-label', `Job ${id}`)
  })

  it('shows step, item and the job’s own estimate', () => {
    const { el, send } = mountJob()
    send('progress', { step: 3, total: 10, label: 'Scanning library', item: 'Hollow Knight', eta_seconds: 9 })
    expect(sel(el, '.job-label')).toHaveTextContent('Scanning library')
    expect(text(el)).toContain('Step 3 of 10')
    expect(sel(el, '.job-item')).toHaveTextContent('Hollow Knight')
    expect(sel(el, '.job-eta')).toHaveTextContent('about 0:09 left')
    expect(sel(el, '[role=progressbar]')).toHaveAttribute('aria-valuenow', '30')
  })

  it('says "working…" for an unbounded phase', () => {
    const { el, send } = mountJob()
    send('progress', { step: 4, total: null, label: 'Reading' })
    expect(sel(el, '.job-eta')).toHaveTextContent('working…')
    expect(text(el)).not.toMatch(/Step \d/)
    expect(sel(el, '[role=progressbar]')).not.toHaveAttribute('aria-valuenow')
  })

  it('shows no estimate for an empty total', () => {
    const { el, send } = mountJob()
    send('progress', { step: 0, total: 0, label: 'Preparing' })
    expect(sel(el, '.job-eta')?.textContent).toBe('')
    expect(sel(el, '[role=progressbar]')).not.toHaveAttribute('aria-valuenow')
  })

  it('extrapolates the remaining time from the pace when the job gives none', async () => {
    vi.useFakeTimers({ now: Date.parse('2026-10-10T10:00:00Z') })
    const { el, send } = mountJob()
    send('progress', { step: 1, total: 5, label: 'Working' })
    await vi.advanceTimersByTimeAsync(10_000)
    send('progress', { step: 2, total: 5, label: 'Working' })
    expect(sel(el, '.job-eta')).toHaveTextContent('about 0:15 left')
  })

  it('falls back to the fetched job’s progress', async () => {
    const { el } = mountJob({ job: { progress: { step: 2, total: 4, label: 'From server' } } })
    await vi.waitFor(() => { expect(sel(el, '.job-label')).toHaveTextContent('From server') })
    expect(sel(el, '.job-eta')?.textContent).toBe('')
  })

  it('shows the connection state', () => {
    const { el, es } = mountJob()
    expect(text(el)).toContain('Reconnecting')
    es.onopen?.()
    expect(text(el)).toContain('Live')
    expect(sel(el, '.dot')).toHaveClass('dot-live')
  })

  it('works without a job-id attribute', () => {
    document.body.innerHTML = '<job-progress></job-progress>'
    expect(document.body.firstElementChild?.querySelector('h3')).toHaveTextContent('Job')
  })
})

describe('<job-progress> waiting for input', () => {
  it('shows the question, pauses, and lets even a non-cancellable job be cancelled', () => {
    const { el, send } = mountJob()
    send('prompt', { prompt_id: 'q', kind: 'text', message: 'Name?' })
    expect(sel(el, 'form')).toBeNull()
    send('state', { state: 'waiting_input' })
    expect(text(el)).toContain('Waiting for your answer')
    expect(sel(el, '.job-eta')).toHaveTextContent('paused')
    expect(sel(el, 'form')).toHaveAttribute('aria-label', 'Job question')
    expect(button(el, 'Cancel job')).toBeInTheDocument()
    expect(sel(el, '[role=progressbar]')?.className).toContain('bar-warning')
  })

  it('keeps one form per prompt, swaps it for a new prompt and drops it when answered', () => {
    const { el, send } = mountJob()
    send('state', { state: 'waiting_input' })
    send('prompt', { prompt_id: 'q1', kind: 'text', message: 'One?' })
    const first = sel(el, 'form')
    send('log', { level: 'info', message: 'noise' })
    expect(sel(el, 'form')).toBe(first)
    send('prompt', { prompt_id: 'q2', kind: 'confirm', message: 'Two?' })
    expect(sel(el, 'form')).not.toBe(first)
    send('state', { state: 'running' })
    expect(sel(el, 'form')).toBeNull()
  })

  it('cancels through the API and shows a failure', async () => {
    const { el, send, routes, id } = mountJob({ cancellable: true })
    routes[`POST /api/jobs/${id}/cancel`] = apiError(409, 'not_cancellable', 'too late')
    await vi.waitFor(() => { expect(sel(el, '.actions')).not.toBeNull() })
    send('state', { state: 'running' })
    button(el, 'Cancel job').click()
    await vi.waitFor(() => { expect(text(el)).toContain('too late') })
  })

  it('shows Cancelling… while the request runs', async () => {
    const { el, routes, id } = mountJob({ cancellable: true })
    routes[`POST /api/jobs/${id}/cancel`] = () => new Promise(() => undefined)
    await vi.waitFor(() => { expect(sel(el, '.actions')).not.toBeNull() })
    button(el, 'Cancel job').click()
    await vi.waitFor(() => { expect(button(el, 'Cancelling…')).toBeDisabled() })
  })
})

describe('<job-progress> when finished', () => {
  it('reports success with the summary, full bar and an open log', () => {
    const { el, send } = mountJob({ cancellable: true })
    send('state', { state: 'succeeded' })
    send('result', { ok: true, summary: 'All 12 scanned' })
    expect(sel(el, '.job-label')).toHaveTextContent('Completed')
    expect(text(el)).toContain('Done')
    expect(text(el)).toContain('All 12 scanned')
    expect(sel(el, '[role=progressbar]')).toHaveAttribute('aria-valuenow', '100')
    expect(sel(el, '[role=progressbar]')?.className).toContain('bar-success')
    expect(text(el)).not.toContain('Cancel job')
    expect(sel(el, 'details')).toHaveAttribute('open')
    expect(text(el)).toContain('No output.')
    expect(sel(el, '.job-sub')).toBeNull()
    expect(sel(el, '.dot')).toBeNull()
  })

  it('reports failure and cancellation', () => {
    const failed = mountJob()
    failed.send('state', { state: 'failed' })
    failed.send('result', { ok: false, summary: 'boom' })
    expect(text(failed.el)).toContain('Did not complete')
    expect(sel(failed.el, '.job-label')).toHaveTextContent('Failed')
    expect(sel(failed.el, '[role=progressbar]')?.className).toContain('bar-danger')
    const cancelled = mountJob()
    cancelled.send('state', { state: 'cancelled' })
    expect(sel(cancelled.el, '.job-label')).toHaveTextContent('Cancelled')
  })
})
