import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSpec } from '../test/fixtures'
import { renderRouted, stubApi } from '../test/harness'
import { System } from './System'

const ROUTES = {
  'GET /api/setup': { configured: true, has_api_key: true, steam_id: '7656119800000000' },
  'GET /api/server': { stale: false, started_at: '2026-10-10T10:00:00Z', version: '1' },
  'GET /api/daemon': { state: 'running', started_at: null, pid: 1, journal_tail: [], restart_available_at: null },
  'GET /api/backups': [],
  'GET /api/commands': [makeSpec('reset'), makeSpec('enforce')],
}

describe('System', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('composes the server, setup, daemon and backup cards', async () => {
    stubApi(ROUTES)
    renderRouted(<System />)
    for (const name of ['Web server', 'Setup', 'Enforcer daemon', 'State backups']) {
      expect(await screen.findByRole('region', { name })).toBeInTheDocument()
    }
    expect(screen.getByText(/no way to stop the enforcer/)).toBeInTheDocument()
  })

  it('summarises setup', async () => {
    stubApi(ROUTES)
    renderRouted(<System />)
    expect(await screen.findByText('Stored (never shown)')).toBeInTheDocument()
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('7656119800000000')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Open setup' }))
  })

  it('reports an unconfigured setup', async () => {
    stubApi({ ...ROUTES, 'GET /api/setup': { configured: false, has_api_key: false, steam_id: null } })
    renderRouted(<System />)
    expect(await screen.findByText('Missing')).toBeInTheDocument()
    expect(screen.getByText('No')).toBeInTheDocument()
  })

  it('shows placeholders until setup loads', async () => {
    stubApi({ ...ROUTES, 'GET /api/setup': () => new Promise(() => {}) })
    renderRouted(<System />)
    const setup = await screen.findByRole('region', { name: 'Setup' })
    expect(setup.textContent?.match(/…/g)).toHaveLength(2)
    expect(setup).toHaveTextContent('—')
  })
})
