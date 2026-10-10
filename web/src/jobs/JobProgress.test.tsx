import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makeSpec } from '../test/fixtures'
import { apiError, FakeEventSource, installEventSource, renderClient, stubApi } from '../test/harness'
import { JobProgress } from './JobProgress'

let n = 0
const ts = '2026-10-10T10:00:00Z'

/** Mount a JobProgress for a fresh job id; `send` pushes SSE events into it. */
function mount(opts: { job?: Parameters<typeof makeJob>[0]; cancellable?: boolean; compact?: boolean; extra?: Record<string, unknown> } = {}) {
  const id = `jp-${++n}`
  const routes: Record<string, unknown> = {
    [`GET /api/jobs/${id}`]: makeJob({ id, command: 'scan', ...opts.job }),
    'GET /api/commands': [makeSpec('scan', { cancellable: opts.cancellable ?? false })],
    ...opts.extra,
  }
  const mock = stubApi(routes)
  renderClient(<JobProgress jobId={id} compact={opts.compact} />)
  const es = FakeEventSource.last
  let seq = 0
  const send = (type: string, body: Record<string, unknown>) => act(() => es.emit(type, { seq: ++seq, ts, type, ...body }))
  return { id, es, send, mock, routes }
}

describe('JobProgress', () => {
  beforeEach(installEventSource)
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('starts from the fetched job and shows "Starting…" before any progress', async () => {
    mount({ job: { state: 'running' } })
    expect(screen.getByText('Starting…')).toBeInTheDocument()
    expect(screen.getByText('Queued')).toBeInTheDocument() // until the job loads
    expect(await screen.findByText('Running')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Scan' })).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('shows step, item and the job’s own estimate', async () => {
    const { send } = mount()
    await send('progress', { step: 3, total: 10, label: 'Scanning library', item: 'Hollow Knight', eta_seconds: 9 })
    expect(screen.getByText('Scanning library', { selector: '.job-label' })).toBeInTheDocument()
    expect(screen.getByText('Step 3 of 10')).toBeInTheDocument()
    expect(screen.getByText('Hollow Knight')).toBeInTheDocument()
    expect(screen.getByText('about 0:09 left')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '30')
  })

  it('says "working…" for an unbounded phase', async () => {
    const { send } = mount()
    await send('progress', { step: 4, total: null, label: 'Reading' })
    expect(screen.getByText('working…')).toBeInTheDocument()
    expect(screen.queryByText(/^Step/)).toBeNull()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('shows nothing for an empty total and no estimate yet', async () => {
    const { send } = mount()
    await send('progress', { step: 0, total: 0, label: 'Preparing' })
    expect(document.querySelector('.job-eta')).toHaveTextContent('')
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  })

  it('extrapolates the remaining time from the pace when the job gives none', async () => {
    vi.useFakeTimers({ now: Date.parse(ts) })
    const { send } = mount()
    await send('progress', { step: 1, total: 5, label: 'Working' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    await send('progress', { step: 2, total: 5, label: 'Working' })
    // 10 s for 2 steps, 3 to go: 15 s.
    expect(screen.getByText('about 0:15 left')).toBeInTheDocument()
  })

  it('has no estimate for the first step of zero', async () => {
    const { send } = mount()
    await send('progress', { step: 0, total: 5, label: 'Working' })
    expect(document.querySelector('.job-eta')).toHaveTextContent('')
  })

  it('falls back to the fetched job’s progress, with a null estimate ignored', async () => {
    mount({ job: { progress: { step: 2, total: 4, label: 'From server', eta_seconds: null as unknown as undefined } } })
    expect(await screen.findByText('From server', { selector: '.job-label' })).toBeInTheDocument()
    expect(document.querySelector('.job-eta')).toHaveTextContent('') // no pace data either
  })

  it('shows the connection state', async () => {
    const { es } = mount()
    expect(screen.getByText('Reconnecting')).toBeInTheDocument()
    act(() => es.onopen?.())
    expect(screen.getByText('Live')).toBeInTheDocument()
  })

  describe('waiting for input', () => {
    it('shows the question, pauses, and lets even a non-cancellable job be cancelled', async () => {
      const { send, mock } = mount({ extra: { 'POST /api/jobs/jp-1/cancel': undefined } })
      mock.mockClear()
      await send('prompt', { prompt_id: 'q', kind: 'text', message: 'Name?' })
      await send('state', { state: 'waiting_input' })
      expect(screen.getByText('Waiting for your answer')).toBeInTheDocument()
      expect(screen.getByText('paused')).toBeInTheDocument()
      expect(screen.getByRole('form', { name: 'Job question' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Cancel job' })).toBeInTheDocument()
    })

    it('cancels through the API and shows a failure', async () => {
      const { send, routes, id } = mount({ cancellable: true })
      routes[`POST /api/jobs/${id}/cancel`] = apiError(409, 'not_cancellable', 'too late')
      await send('state', { state: 'running' })
      await userEvent.click(await screen.findByRole('button', { name: 'Cancel job' }))
      expect(await screen.findByText('too late')).toBeInTheDocument()
    })

    it('shows Cancelling… while the request runs', async () => {
      let release: () => void = () => {}
      const { send, routes, id } = mount({ cancellable: true })
      routes[`POST /api/jobs/${id}/cancel`] = () => new Promise<void>((r) => (release = r))
      await send('state', { state: 'running' })
      await userEvent.click(await screen.findByRole('button', { name: 'Cancel job' }))
      expect(await screen.findByRole('button', { name: 'Cancelling…' })).toBeDisabled()
      await act(async () => release())
    })
  })

  describe('when finished', () => {
    it('reports success with the summary, full bar and an open log', async () => {
      const { send } = mount({ cancellable: true })
      await send('state', { state: 'succeeded' })
      await send('result', { ok: true, summary: 'All 12 scanned' })
      expect(screen.getByText('Completed')).toBeInTheDocument()
      expect(screen.getByText('Done')).toBeInTheDocument()
      expect(screen.getByText('All 12 scanned')).toBeInTheDocument()
      expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
      expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
      expect(document.querySelector('details')).toHaveAttribute('open')
      expect(screen.getByText('No output.')).toBeInTheDocument()
      expect(document.querySelector('.job-sub')).toBeNull()
    })

    it('reports failure and cancellation', async () => {
      const failed = mount()
      await failed.send('state', { state: 'failed' })
      await failed.send('result', { ok: false, summary: 'boom' })
      expect(screen.getByText('Did not complete')).toBeInTheDocument()
      expect(screen.getByText('Failed', { selector: '.job-label' })).toBeInTheDocument()
      expect(screen.getByRole('progressbar').className).toContain('bar-danger')
      const cancelled = mount()
      await cancelled.send('state', { state: 'cancelled' })
      expect(screen.getByText('Cancelled', { selector: '.job-label' })).toBeInTheDocument()
    })

    it('uses the success tone', async () => {
      const { send } = mount()
      await send('state', { state: 'succeeded' })
      expect(screen.getByRole('progressbar').className).toContain('bar-success')
    })
  })

  describe('log', () => {
    it('lists lines with their time and counts them', async () => {
      const { send } = mount()
      await send('log', { level: 'info', message: 'hello' })
      await send('log', { level: 'warning', message: 'careful' })
      expect(screen.getByText('Log (2 lines)')).toBeInTheDocument()
      expect(screen.getByText('hello')).toBeInTheDocument()
      expect(screen.getAllByText('10:00:00')).toHaveLength(2)
      expect(document.querySelector('details')).not.toHaveAttribute('open')
      expect(screen.queryByText('No output yet.')).toBeNull()
    })

    it('opens by itself on an error line, but not in compact mode', async () => {
      const full = mount()
      await full.send('log', { level: 'error', message: 'bad' })
      expect(document.querySelector('details')).toHaveAttribute('open')
    })

    it('stays closed in compact mode', async () => {
      const { send } = mount({ compact: true })
      await send('log', { level: 'error', message: 'bad' })
      expect(document.querySelector('details')).not.toHaveAttribute('open')
      expect(document.querySelector('section')).toHaveClass('job-compact')
    })

    it('says nothing has been printed yet', () => {
      mount()
      expect(screen.getByText('No output yet.')).toBeInTheDocument()
    })
  })
})
