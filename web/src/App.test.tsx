import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { refreshAfterJob } from './api/queries'
import { hub } from './jobs/hub'
import { router } from './router'
import { makeBudget, makeDataset } from './test/factories'
import { makeInstalled, makeJob, makeLibGame, makeSpec, makeStatus } from './test/fixtures'
import { installEventSource, stubApi } from './test/harness'

const routes = (over: Record<string, unknown> = {}) => ({
  'GET /api/setup': { configured: true, has_api_key: true, steam_id: '76561198000000000' },
  'GET /api/server': { stale: false, started_at: '2026-10-10T10:00:00Z', version: '1' },
  'GET /api/daemon': { state: 'running', started_at: null, pid: 1, journal_tail: [], restart_available_at: null },
  'GET /api/status': makeStatus(),
  'GET /api/budget': makeBudget(),
  'GET /api/dataset': makeDataset(),
  'GET /api/stats': { default_summary: makeDataset().default_summary, pace_vs_hltb: null },
  'GET /api/installed': { games: [makeInstalled()] },
  'GET /api/library': { games: [makeLibGame()] },
  'GET /api/backups': [],
  'GET /api/jobs': [],
  'GET /api/jobs/abc': makeJob({ id: 'abc', command: 'scan' }),
  'GET /api/commands': [makeSpec('scan'), makeSpec('done')],
  ...over,
})

// The router only follows history while a RouterProvider is mounted, so
// awaiting router.navigate() before render would never settle: set the URL,
// mount, then have the router read it.
async function openAt(path: string) {
  router.history.replace(path)
  const view = render(<App />)
  await act(async () => {
    await router.load()
  })
  return view
}

describe('App', () => {
  beforeEach(installEventSource)
  afterEach(() => {
    router.history.replace('/')
    vi.unstubAllGlobals()
  })

  it('refreshes every cached view when any job ends', () => {
    expect(hub.onTerminal).toBe(refreshAfterJob)
  })

  it('opens on the dashboard inside the shell', async () => {
    stubApi(routes())
    await openAt('/')
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Sections' })).toBeInTheDocument()
    expect(await screen.findByText('Hollow Knight')).toBeInTheDocument()
  })

  it('walks the sidebar to another section', async () => {
    stubApi(routes())
    await openAt('/')
    await userEvent.click(await screen.findByRole('link', { name: /Store/ }))
    expect(await screen.findByRole('heading', { name: 'Store' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/store')
  })

  it('shows the library at /library', async () => {
    stubApi(routes())
    await openAt('/library')
    expect(await screen.findByText('1 of 1 games')).toBeInTheDocument()
  })

  describe('/gaming search', () => {
    const modes: [string, string, string][] = [
      ['true', '?demo=true', 'Show production budget'],
      ['1', '?demo=1', 'Show production budget'],
      ['"1"', '?demo=%221%22', 'Show production budget'],
      ['anything else', '?demo=maybe', 'Show demo budget'],
      ['absent', '', 'Show demo budget'],
    ]
    it.each(modes)('demo=%s', async (_label, query, link) => {
      stubApi(routes({ 'GET /api/budget?demo=1': makeBudget() }))
      await openAt(`/gaming${query}`)
      expect(await screen.findByRole('link', { name: link })).toBeInTheDocument()
    })
  })

  it('routes /jobs/$jobId to the job’s page', async () => {
    stubApi(routes())
    await openAt('/jobs/abc')
    expect(await screen.findByRole('heading', { name: 'Scan', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('abc')).toBeInTheDocument()
  })

  it('shows the not-found screen inside the shell', async () => {
    stubApi(routes())
    await openAt('/nope')
    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Sections' })).toBeInTheDocument()
  })

  it('redirects an unconfigured install to Setup', async () => {
    stubApi(routes({ 'GET /api/setup': { configured: false, has_api_key: false, steam_id: null } }))
    await openAt('/picks')
    await waitFor(() => expect(router.state.location.pathname).toBe('/setup'))
    expect(await screen.findByText('Not configured yet')).toBeInTheDocument()
  })
})
