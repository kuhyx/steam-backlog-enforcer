import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { apiError, renderClient, stubApi } from '../test/harness'
import { HealthBadges, StaleBanner } from './Health'

const server = (over = {}) => ({ stale: false, started_at: '2026-10-10T10:00:00Z', version: '1.2.3', ...over })
const daemon = (state: string) => ({ state, started_at: null, pid: null, journal_tail: [], restart_available_at: null })

describe('HealthBadges', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is neutral while nothing has loaded', () => {
    stubApi({ 'GET /api/server': () => new Promise(() => {}), 'GET /api/daemon': () => new Promise(() => {}) })
    renderClient(<HealthBadges />)
    expect(screen.getByText('Server ok')).toBeInTheDocument()
    expect(screen.getByText('Daemon …')).toHaveClass('pill-neutral')
    expect(screen.getByText('Server ok')).not.toHaveAttribute('title')
  })

  it('shows a healthy server with its version, and a running daemon', async () => {
    stubApi({ 'GET /api/server': server(), 'GET /api/daemon': daemon('running') })
    renderClient(<HealthBadges />)
    expect(await screen.findByText('Daemon running')).toHaveClass('pill-success')
    expect(screen.getByText('Server ok')).toHaveAttribute('title', 'v1.2.3')
  })

  it('flags a stale server and a restarting daemon', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }), 'GET /api/daemon': daemon('restarting') })
    renderClient(<HealthBadges />)
    expect(await screen.findByText('Server stale')).toHaveClass('pill-warning')
    expect(screen.getByText('Daemon restarting')).toHaveClass('pill-warning')
  })

  it('flags a dead server and an unreachable daemon', async () => {
    stubApi({ 'GET /api/server': apiError(500, 'op_failed'), 'GET /api/daemon': daemon('unreachable') })
    renderClient(<HealthBadges />)
    expect(await screen.findByText('Server down')).toHaveClass('pill-danger')
    expect(await screen.findByText('Daemon unreachable')).toHaveClass('pill-danger')
  })
})

describe('StaleBanner', () => {
  const reload = vi.fn()
  afterEach(() => {
    reload.mockClear()
    vi.unstubAllGlobals()
  })

  it('is absent while the code is current, or unknown', async () => {
    stubApi({ 'GET /api/server': server() })
    renderClient(<StaleBanner />)
    await act(async () => {})
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('offers a restart, then reloads once the new process answers', async () => {
    vi.stubGlobal('location', { ...window.location, reload })
    const routes: Record<string, unknown> = { 'GET /api/server': server({ stale: true }), 'POST /api/server/restart': undefined }
    stubApi(routes)
    renderClient(<StaleBanner />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByRole('button', { name: 'Restarting…' })).toBeDisabled()
    expect(reload).not.toHaveBeenCalled()
    routes['GET /api/server'] = server({ stale: false, started_at: '2026-10-10T11:00:00Z' })
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['server'] })
    })
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
  })

  it('shows why a restart was refused', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }), 'POST /api/server/restart': apiError(429, 'rate_limited', 'too soon') })
    renderClient(<StaleBanner />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByText('too soon')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart server' })).toBeEnabled()
  })
})
