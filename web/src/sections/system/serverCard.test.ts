import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { q } from '../../api/queries'
import { ServerRestart } from '../../shell/serverRestart'
import { apiError, mount, stubApi } from '../../test/harness'
import './serverCard'

const server = (over = {}) => ({ stale: false, started_at: '2026-10-10T10:00:00Z', version: '9.9.9', ...over })

describe('server-card', () => {
  it('shows version, start time and that the code is current', async () => {
    stubApi({ 'GET /api/server': server() })
    mount('<server-card></server-card>')
    expect(await screen.findByText('9.9.9')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Web server' })).toBeInTheDocument()
    expect(screen.getByText('current')).toBeInTheDocument()
    expect(screen.queryByText('Stale')).toBeNull()
  })

  it('flags stale code', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }) })
    mount('<server-card></server-card>')
    expect(await screen.findByText('Stale')).toBeInTheDocument()
    expect(screen.getByText('stale')).toBeInTheDocument()
  })

  it('shows loading, then a failure', async () => {
    stubApi({ 'GET /api/server': () => new Promise(() => undefined) })
    mount('<server-card></server-card>')
    expect(await screen.findByText(/Loading server health/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/server': apiError(500, 'op_failed', 'server broke') })
    mount('<server-card></server-card>')
    expect(await screen.findByText('server broke')).toBeInTheDocument()
  })

  it('restarts, then waits for the new process', async () => {
    stubApi({ 'GET /api/server': server(), 'POST /api/server/restart': undefined })
    mount('<server-card></server-card>')
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByRole('button', { name: /Restarting… the page reloads/ })).toBeDisabled()
  })

  it('keeps the button node across polls', async () => {
    stubApi({ 'GET /api/server': server() })
    mount('<server-card></server-card>')
    const button = await screen.findByRole('button', { name: 'Restart server' })
    q.server.set(server({ version: '10' }))
    expect(await screen.findByText('10')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart server' })).toBe(button)
  })

  it('shows a refused restart', async () => {
    stubApi({ 'GET /api/server': server(), 'POST /api/server/restart': apiError(429, 'rate_limited', 'too often') })
    mount('<server-card></server-card>')
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByText('too often')).toBeInTheDocument()
  })

  it('stops waiting for the restart when it leaves the page', async () => {
    const dispose = vi.spyOn(ServerRestart.prototype, 'dispose')
    stubApi({ 'GET /api/server': server() })
    mount('<server-card></server-card>')
    await screen.findByText('9.9.9')
    document.body.replaceChildren()
    expect(dispose).toHaveBeenCalledOnce()
    dispose.mockRestore()
  })
})
