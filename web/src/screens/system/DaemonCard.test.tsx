import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RunnerContext } from '../../commands/runnerContext'
import { makeSpec } from '../../test/fixtures'
import { apiError, renderRouted, stubApi } from '../../test/harness'
import { DaemonCard } from './DaemonCard'

const daemon = (over = {}) => ({
  state: 'running',
  started_at: '2026-10-10T10:00:00Z',
  pid: 4242,
  journal_tail: ['line one', 'line two'],
  restart_available_at: null,
  ...over,
})
const run = vi.fn()
const show = (reply: unknown) => {
  stubApi({ 'GET /api/daemon': reply, 'GET /api/commands': [makeSpec('enforce')] })
  return renderRouted(
    <RunnerContext.Provider value={{ run, openPalette: () => {} }}>
      <DaemonCard />
    </RunnerContext.Provider>,
  )
}

describe('DaemonCard', () => {
  afterEach(() => {
    run.mockClear()
    vi.unstubAllGlobals()
  })

  it('shows state, pid, uptime and the journal', async () => {
    show(daemon())
    expect(await screen.findByText('4242')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText(/ago/)).toBeInTheDocument()
    expect(screen.getByLabelText('Daemon journal (live)')).toHaveTextContent(/line one\s+line two/)
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
    expect(screen.getByText('No journal lines.')).toBeInTheDocument()
    expect(screen.getAllByText('—')).toHaveLength(2)
  })

  it('offers the demo run', async () => {
    show(daemon())
    await userEvent.click(await screen.findByRole('button', { name: 'Demo run (enforce --demo)…' }))
    expect(run).toHaveBeenCalledWith('enforce', { demo: 1 })
  })

  it('shows loading, then a failure', async () => {
    show(() => new Promise(() => {}))
    expect(await screen.findByText(/Loading daemon status/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    show(apiError(500, 'op_failed', 'daemon broke'))
    expect(await screen.findByText('daemon broke')).toBeInTheDocument()
  })
})
