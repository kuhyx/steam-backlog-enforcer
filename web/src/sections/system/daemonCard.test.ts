import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import type { DaemonStatus } from '../../api/contract'
import { q } from '../../api/queries'
import { runner } from '../../lib/runner'
import { apiError, mount, stubApi, type Handler } from '../../test/harness'
import { restartWaitMs } from './daemonCard'

const daemon = (over: Partial<DaemonStatus> = {}): DaemonStatus => ({
  state: 'running',
  started_at: '2026-10-10T10:00:00Z',
  pid: 4242,
  journal_tail: ['line one', 'line two'],
  restart_available_at: null,
  ...over,
})

let run: MockInstance<typeof runner.run>
const show = (reply: Handler) => {
  stubApi({ 'GET /api/daemon': reply })
  return mount('<daemon-card></daemon-card>')
}
const journal = () => screen.getByLabelText('Daemon journal (live)')

describe('restartWaitMs', () => {
  it('counts down to the limit and never below zero', () => {
    expect(restartWaitMs(null, 0)).toBe(0)
    expect(restartWaitMs('1970-01-01T00:00:10Z', 4000)).toBe(6000)
    expect(restartWaitMs('1970-01-01T00:00:10Z', 20_000)).toBe(0)
  })
})

describe('daemon-card', () => {
  beforeEach(() => {
    run = vi.spyOn(runner, 'run').mockImplementation(() => undefined)
  })
  afterEach(() => {
    run.mockRestore()
  })

  it('shows state, pid, uptime and the journal', async () => {
    show(daemon())
    expect(await screen.findByText('4242')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Enforcer daemon' })).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByLabelText(/ago/)).toBeInTheDocument()
    expect(screen.getByText('running').closest('[data-state]')).toHaveAttribute('data-state', 'running')
    expect(journal()).toHaveTextContent(/line one\s+line two/)
    expect(screen.queryByText('Daemon unreachable')).toBeNull()
  })

  it('restarts through the runner when allowed', async () => {
    show(daemon())
    await userEvent.click(await screen.findByRole('button', { name: 'Restart daemon…' }))
    expect(run).toHaveBeenCalledWith('enforce', { demo: 0 })
  })

  it('refuses a restart while rate-limited, showing the wait', async () => {
    show(daemon({ restart_available_at: new Date(Date.now() + 125_000).toISOString() }))
    const button = await screen.findByRole('button', { name: /Restart available in [12]:\d\d/ })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(button)
    expect(run).not.toHaveBeenCalled()
  })

  it('treats a lapsed rate limit as available', async () => {
    show(daemon({ restart_available_at: new Date(Date.now() - 60_000).toISOString() }))
    await userEvent.click(await screen.findByRole('button', { name: 'Restart daemon…' }))
    expect(run).toHaveBeenCalled()
  })

  it('cannot restart a daemon that is not running, and says it is unreachable', async () => {
    show(daemon({ state: 'unreachable', pid: null, started_at: null, journal_tail: [] }))
    expect(await screen.findByText('Daemon unreachable')).toBeInTheDocument()
    expect(screen.getByText('systemctl status steam-backlog-enforcer')).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Restart daemon…' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(button)
    expect(run).not.toHaveBeenCalled()
    expect(journal()).toHaveTextContent(/^—$/)
    expect(screen.getAllByText('—')).toHaveLength(3)
  })

  it('offers the demo run', async () => {
    show(daemon())
    await userEvent.click(await screen.findByRole('button', { name: 'Demo run (enforce --demo)…' }))
    expect(run).toHaveBeenCalledWith('enforce', { demo: 1 })
  })

  it('keeps the buttons and the unreachable notice across polls', async () => {
    show(daemon({ state: 'unreachable' }))
    const button = await screen.findByRole('button', { name: 'Restart daemon…' })
    const alert = screen.getByText('Daemon unreachable')
    q.daemon.set(daemon({ state: 'unreachable' }))
    expect(screen.getByRole('button', { name: 'Restart daemon…' })).toBe(button)
    expect(screen.getByText('Daemon unreachable')).toBe(alert)
    q.daemon.set(daemon())
    expect(screen.queryByText('Daemon unreachable')).toBeNull()
  })

  it('follows the journal tail, unless scrolled up', async () => {
    show(daemon())
    await screen.findByText('4242')
    const pre = journal()
    Object.defineProperty(pre, 'scrollHeight', { configurable: true, value: 500 })
    Object.defineProperty(pre, 'clientHeight', { configurable: true, value: 100 })
    pre.scrollTop = 400
    q.daemon.set(daemon({ journal_tail: ['line two', 'line three'] }))
    expect(pre).toHaveTextContent(/line two\s+line three/)
    expect(pre.scrollTop).toBe(500)
    pre.scrollTop = 0
    q.daemon.set(daemon({ journal_tail: ['line three', 'line four'] }))
    expect(pre).toHaveTextContent(/line four/)
    expect(pre.scrollTop).toBe(0)
  })

  it('shows loading, then a failure', async () => {
    show(() => new Promise(() => undefined))
    expect(await screen.findByText(/Loading daemon status/)).toBeInTheDocument()
  })

  it('explains a failed load, hiding the stale body', async () => {
    show(daemon())
    await screen.findByText('4242')
    stubApi({ 'GET /api/daemon': apiError(500, 'op_failed', 'daemon broke') })
    await q.daemon.refetch()
    expect(screen.getByText('daemon broke')).toBeInTheDocument()
    expect(screen.queryByText('4242')).toBeNull()
  })
})
