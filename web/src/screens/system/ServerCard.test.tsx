import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, renderClient, stubApi } from '../../test/harness'
import { ServerCard } from './ServerCard'

const server = (over = {}) => ({ stale: false, started_at: '2026-10-10T10:00:00Z', version: '9.9.9', ...over })

describe('ServerCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows version, start time and that the code is current', async () => {
    stubApi({ 'GET /api/server': server() })
    renderClient(<ServerCard />)
    expect(await screen.findByText('9.9.9')).toBeInTheDocument()
    expect(screen.getByText('current')).toBeInTheDocument()
    expect(screen.queryByText('Stale')).toBeNull()
  })

  it('flags stale code', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }) })
    renderClient(<ServerCard />)
    expect(await screen.findByText('Stale')).toBeInTheDocument()
    expect(screen.getByText('stale')).toBeInTheDocument()
  })

  it('shows loading, then a failure', async () => {
    stubApi({ 'GET /api/server': () => new Promise(() => {}) })
    renderClient(<ServerCard />)
    expect(await screen.findByText(/Loading server health/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/server': apiError(500, 'op_failed', 'server broke') })
    renderClient(<ServerCard />)
    expect(await screen.findByText('server broke')).toBeInTheDocument()
  })

  it('restarts, then waits for the new process', async () => {
    stubApi({ 'GET /api/server': server(), 'POST /api/server/restart': undefined })
    renderClient(<ServerCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByRole('button', { name: /Restarting… the page reloads/ })).toBeDisabled()
  })

  it('shows a refused restart', async () => {
    stubApi({ 'GET /api/server': server(), 'POST /api/server/restart': apiError(429, 'rate_limited', 'too often') })
    renderClient(<ServerCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Restart server' }))
    expect(await screen.findByText('too often')).toBeInTheDocument()
  })
})
