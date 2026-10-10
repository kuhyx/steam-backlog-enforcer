import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSpec, makeStatus } from '../test/fixtures'
import { apiError, renderRouted, stubApi } from '../test/harness'
import { NotFound } from './NotFound'
import { Picks } from './Picks'
import { Store } from './Store'

const SPECS = ['check', 'done', 'pick', 'scan', 'pick-manual', 'abandon-pick', 'unblock', 'buy-dlc', 'add-exception'].map((n) =>
  makeSpec(n as 'check'),
)

describe('NotFound', () => {
  it('points home', async () => {
    const { router } = renderRouted(<NotFound />)
    const link = await screen.findByRole('link', { name: 'Back to the dashboard' })
    await userEvent.click(link)
    expect(router.state.location.pathname).toBe('/')
    expect(screen.getByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })
})

describe('Picks', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists manual picks, each with its abandon button', async () => {
    stubApi({
      'GET /api/commands': SPECS,
      'GET /api/status': makeStatus({ manual_picks: [{ app_id: 5, name: 'Five', age_days: 3 }, { app_id: 6, name: 'Six', age_days: 0 }] }),
    })
    renderRouted(<Picks />)
    expect(await screen.findByText('Five')).toBeInTheDocument()
    expect(screen.getByText(/picked 3 d ago · 5/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Abandon…' })).toHaveLength(2)
    expect(screen.queryByText(/No manual picks/)).toBeNull()
    expect(screen.getByText('Hollow Knight', { selector: 'strong' })).toBeInTheDocument()
  })

  it('invites locking in a game when there are none', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': makeStatus({ current_game_name: null }) })
    renderRouted(<Picks />)
    expect(await screen.findByText(/No manual picks/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Abandon a pick by app id…' })).toBeInTheDocument()
    expect(screen.getByText('Which game you are playing, and how to move on.')).toBeInTheDocument()
    for (const label of ['Check', 'Done', 'Pick…', 'Scan', 'Lock in a game…']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('shows loading, then a failure', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': () => new Promise(() => {}) })
    renderRouted(<Picks />)
    expect(await screen.findByText(/Loading status/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': apiError(500, 'op_failed', 'status broke') })
    renderRouted(<Picks />)
    expect(await screen.findByText('status broke')).toBeInTheDocument()
  })
})

describe('Store', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says the store is blocked', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': makeStatus({ store_blocked: true }) })
    renderRouted(<Store />)
    expect(await screen.findByText('Store blocked')).toBeInTheDocument()
    expect(screen.getByText(/capped at 30 minutes/)).toBeInTheDocument()
    for (const label of ['Unblock…', 'Buy DLC…', 'Request exception…']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('warns when it is open', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': makeStatus({ store_blocked: false }) })
    renderRouted(<Store />)
    expect(await screen.findByText('Store unblocked')).toBeInTheDocument()
    expect(screen.getByText(/re-blocks automatically/)).toBeInTheDocument()
  })

  it('shows no notice until the status is known', async () => {
    stubApi({ 'GET /api/commands': SPECS, 'GET /api/status': () => new Promise(() => {}) })
    renderRouted(<Store />)
    await screen.findByRole('heading', { name: 'Store' })
    expect(screen.queryByRole('status')).toBeNull()
  })
})
