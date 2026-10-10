import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeBudget, makeBudgetToday } from '../test/factories'
import { makeJob, makeSpec, makeStatus } from '../test/fixtures'
import { apiError, renderRouted, stubApi } from '../test/harness'
import { Dashboard } from './Dashboard'

const base = (over: Record<string, unknown> = {}) => ({
  'GET /api/status': makeStatus(),
  'GET /api/budget': makeBudget(),
  'GET /api/jobs': [],
  'GET /api/commands': [makeSpec('done'), makeSpec('install'), makeSpec('pick'), makeSpec('scan'), makeSpec('check')],
  ...over,
})
const show = (over: Record<string, unknown> = {}) => {
  stubApi(base(over))
  return renderRouted(<Dashboard />)
}
const fact = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling!

describe('Dashboard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('offers the quick actions', async () => {
    show()
    expect(await screen.findByRole('button', { name: 'I got an achievement' })).toBeInTheDocument()
    for (const name of ['Install assigned', 'Pick next', 'Scan']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
  })

  describe('assignment', () => {
    it('summarises a healthy state', async () => {
      show()
      expect(await screen.findByText('Hollow Knight')).toBeInTheDocument()
      expect(fact('Installed')).toHaveTextContent('Yes')
      expect(fact('Games finished')).toHaveTextContent('3')
      expect(fact('Store')).toHaveTextContent('Blocked')
      expect(fact('Installed games')).toHaveTextContent('4')
      expect(fact('Total block')).toHaveTextContent('Off')
      expect(fact('Manual picks')).toHaveTextContent('None')
    })

    it('warns about an uninstalled assignment, open store, total block and picks', async () => {
      show({
        'GET /api/status': makeStatus({
          current_game_name: null,
          assigned_game_installed: false,
          store_blocked: false,
          total_block: { active: true, days_remaining: 5, until: null },
          manual_picks: [{ app_id: 1, name: 'Alpha', age_days: 2 }, { app_id: 2, name: 'Beta', age_days: 9 }],
        }),
      })
      expect(await screen.findByText('Nothing assigned')).toBeInTheDocument()
      expect(fact('Installed')).toHaveTextContent('No — install it from Library')
      expect(fact('Store')).toHaveTextContent('Unblocked')
      expect(fact('Total block')).toHaveTextContent('5 days left')
      expect(fact('Manual picks')).toHaveTextContent('Alpha (2 d), Beta (9 d)')
    })

    it('shows loading, then an error', async () => {
      show({ 'GET /api/status': () => new Promise(() => {}) })
      expect(await screen.findByText(/Loading status/)).toBeInTheDocument()
    })

    it('explains a failed load', async () => {
      show({ 'GET /api/status': apiError(500, 'op_failed', 'status broke') })
      expect(await screen.findByText('status broke')).toBeInTheDocument()
    })
  })

  describe('gaming today', () => {
    it('shows time left and what is billing', async () => {
      show()
      expect(await screen.findByText(/left of/)).toBeInTheDocument()
      expect(screen.getByText('Now: Hollow Knight')).toBeInTheDocument()
      expect(screen.getByRole('progressbar', { name: 'Budget used' }).className).toContain('bar-accent')
      expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute('href', '/gaming')
    })

    it('says nothing is billing', async () => {
      show({ 'GET /api/budget': makeBudget({ session: { ...makeBudget().session, billing_label: '' } }) })
      expect(await screen.findByText('Now: nothing billing')).toBeInTheDocument()
    })

    it('warns when the day is almost used, and reports a block', async () => {
      show({ 'GET /api/budget': makeBudget({ today: makeBudgetToday({ fraction_used: 0.9 }) }) })
      expect(await screen.findByRole('progressbar', { name: 'Budget used' })).toHaveClass('bar-warning')
    })

    it('reports a blocked day', async () => {
      show({ 'GET /api/budget': makeBudget({ today: makeBudgetToday({ blocked: true, fraction_used: 1 }) }) })
      expect(await screen.findByText('Blocked for today.')).toBeInTheDocument()
      expect(screen.getByRole('progressbar', { name: 'Budget used' })).toHaveClass('bar-danger')
    })

    it('shows the budget error, or a default, when there is no today', async () => {
      show({ 'GET /api/budget': makeBudget({ today: null, error: 'state file unreadable' }) })
      expect(await screen.findByText('state file unreadable')).toBeInTheDocument()
    })

    it('has a default message too', async () => {
      show({ 'GET /api/budget': makeBudget({ today: null, error: null }) })
      expect(await screen.findByText('Budget state unavailable.')).toBeInTheDocument()
    })

    it('shows loading, then a request error', async () => {
      show({ 'GET /api/budget': () => new Promise(() => {}) })
      expect(await screen.findByText(/Loading budget/)).toBeInTheDocument()
    })

    it('explains a failed load', async () => {
      show({ 'GET /api/budget': apiError(500, 'op_failed', 'budget broke') })
      expect(await screen.findByText('API returned 500 Error')).toBeInTheDocument()
    })
  })

  describe('recent jobs', () => {
    it('invites running one when there are none', async () => {
      show()
      expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'All jobs' })).toHaveAttribute('href', '/jobs')
    })

    it('lists five with summary, progress or nothing', async () => {
      const jobs = [
        makeJob({ id: 'a', command: 'scan', state: 'succeeded', summary: 'Scanned 12' }),
        makeJob({ id: 'b', command: 'check', progress: { step: 1, total: 2, label: 'Checking games' } }),
        makeJob({ id: 'c', command: 'done' }),
        makeJob({ id: 'd' }),
        makeJob({ id: 'e' }),
        makeJob({ id: 'f' }),
      ]
      show({ 'GET /api/jobs': jobs })
      expect(await screen.findByText('Scanned 12')).toBeInTheDocument()
      expect(screen.getByText('Checking games')).toBeInTheDocument()
      expect(document.querySelectorAll('.rows .row-link')).toHaveLength(5)
      expect(document.querySelector('a[href="/jobs/a"]')).toHaveTextContent('Scan')
    })

    it('explains a failed load', async () => {
      show({ 'GET /api/jobs': apiError(500, 'op_failed', 'jobs broke') })
      expect(await screen.findByText('jobs broke')).toBeInTheDocument()
    })
  })
})
