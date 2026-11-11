import { screen, waitFor, within } from '@testing-library/dom'
import { describe, expect, it, vi } from 'vitest'
import { makeBudget, makeBudgetToday } from '../test/factories'
import { makeJob, makeSpec, makeStatus } from '../test/fixtures'
import { apiError, mount, stubApi, type Handler } from '../test/harness'
import { blockSecondsLeft } from './dashboard'

const daemon = (fast_installs: unknown[] = []) => ({
  state: 'running',
  started_at: null,
  pid: 1,
  journal_tail: [],
  restart_available_at: null,
  fast_installs,
})
const bg3 = { app_id: 1086940, name: "Baldur's Gate 3", phase: 'downloading depot 3/8', percent: 46.9, elapsed_seconds: 312 }
const base = (over: Record<string, Handler> = {}): Record<string, Handler> => ({
  'GET /api/status': makeStatus(),
  'GET /api/daemon': daemon(),
  'GET /api/budget': makeBudget(),
  'GET /api/jobs': [],
  'GET /api/commands': [makeSpec('done'), makeSpec('install'), makeSpec('pick'), makeSpec('scan'), makeSpec('check')],
  ...over,
})

// The body of src/pages/index.astro.
const PAGE = `<main>
  <header class="page-head">
    <command-button name="done" label="I got an achievement" tone="primary"></command-button>
    <command-button name="install" label="Install assigned"></command-button>
    <command-button name="pick" label="Pick next"></command-button>
    <command-button name="scan" label="Scan"></command-button>
  </header>
  <div class="grid-2"><dashboard-status></dashboard-status><budget-glance></budget-glance></div>
  <fast-installs></fast-installs>
  <recent-jobs></recent-jobs>
</main>`

const show = (over: Record<string, Handler> = {}) => {
  const mock = stubApi(base(over))
  mount(PAGE)
  return mock
}
// A fact's term is a glyph whose label is spoken (sr-only).
const fact = (label: string) => screen.getByText(label, { selector: 'dt .sr-only' }).closest('dt')?.nextElementSibling as HTMLElement
const box = (name: string) => screen.getByRole('region', { name })

describe('Dashboard', () => {
  it('offers the quick actions, enabled once the catalog loads', async () => {
    show()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'I got an achievement' })).toHaveAttribute('aria-disabled', 'false')
    })
    expect(screen.getByRole('button', { name: 'I got an achievement' })).toHaveClass('btn-primary')
    for (const name of ['Install assigned', 'Pick next', 'Scan']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-disabled', 'false')
    }
  })

  describe('assignment', () => {
    it('summarises a healthy state', async () => {
      show()
      expect(await screen.findByText('Hollow Knight')).toHaveClass('hero-game')
      expect(fact('Installed')).toHaveTextContent('Yes')
      expect(fact('Games finished')).toHaveTextContent('3')
      expect(fact('Store')).toHaveTextContent('Blocked')
      expect(fact('Installed games')).toHaveTextContent('4')
      expect(fact('Total block')).toHaveTextContent('Off')
      expect(fact('Manual picks')).toHaveTextContent('None')
      // The aside is its own <command-button>, so it follows the catalog.
      expect(await within(box('Assignment')).findByRole('button', { name: 'Check now' })).toHaveAttribute('aria-disabled', 'false')
    })

    it('warns about an uninstalled assignment, open store, total block and picks', async () => {
      show({
        'GET /api/status': makeStatus({
          current_game_name: null,
          assigned_game_installed: false,
          store_blocked: false,
          total_block: { active: true, days_remaining: 5, until: null },
          manual_picks: [
            { app_id: 1, name: 'Alpha', age_days: 2 },
            { app_id: 2, name: 'Beta', age_days: 9 },
          ],
        }),
      })
      expect(await screen.findByText('Nothing assigned')).toBeInTheDocument()
      expect(fact('Installed')).toHaveTextContent('No — install it from Library')
      expect(fact('Store')).toHaveTextContent('Unblocked')
      expect(fact('Total block')).toHaveTextContent('5d 0h left')
      expect(fact('Total block').querySelector('.text-danger')).not.toBeNull()
      expect(fact('Manual picks')).toHaveTextContent('Alpha (2 d), Beta (9 d)')
    })

    it('counts the total block down from until, every second', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true, now: Date.parse('2026-10-23T10:00:00Z') })
      show({ 'GET /api/status': makeStatus({ total_block: { active: true, days_remaining: 0, until: '2026-10-23T11:08:02Z' } }) })
      expect(await screen.findByText('1h 8m left')).toBeInTheDocument()
      const check = screen.getByRole('button', { name: 'Check now' })
      // The jump alone re-renders nothing; the 1 s tick picks it up, then
      // every further tick takes exactly one second off.
      vi.setSystemTime(Date.parse('2026-10-23T11:07:58Z'))
      expect(fact('Total block')).toHaveTextContent('1h 8m left')
      vi.advanceTimersByTime(1000)
      // Painted ⏳ + number; "left" is spoken (sr-only).
      const first = Number(/^(\d)s left$/.exec(fact('Total block').querySelector('.sr-only')?.textContent ?? '')?.[1])
      expect([3, 4]).toContain(first)
      vi.advanceTimersByTime(1000)
      expect(fact('Total block')).toHaveTextContent(`${first - 1}s left`)
      // Only the countdown ticks: the card and its button are not rebuilt.
      expect(screen.getByRole('button', { name: 'Check now' })).toBe(check)
    })

    it('shows loading while status is in flight', async () => {
      show({ 'GET /api/status': () => new Promise(() => undefined) })
      expect(await screen.findByText(/Loading status/)).toBeInTheDocument()
      expect(box('Assignment')).toBeInTheDocument()
    })

    it('explains a failed load', async () => {
      show({ 'GET /api/status': apiError(500, 'op_failed', 'status broke') })
      expect(await screen.findByText('status broke')).toBeInTheDocument()
    })
  })

  describe('<block-countdown>', () => {
    it('is empty until status arrives', () => {
      stubApi({ 'GET /api/status': () => new Promise(() => undefined) })
      expect(mount('<block-countdown></block-countdown>')).toBeEmptyDOMElement()
    })
  })

  describe('blockSecondsLeft', () => {
    it('prefers until, else days_remaining', () => {
      expect(blockSecondsLeft({ active: true, days_remaining: 9, until: '2026-10-23T11:00:00Z' }, Date.parse('2026-10-23T10:00:00Z'))).toBe(3600)
      expect(blockSecondsLeft({ active: true, days_remaining: 0.5, until: null })).toBe(43_200)
    })
  })

  describe('fast install', () => {
    it('shows a daemon-started run with its depot percent', async () => {
      show({ 'GET /api/daemon': daemon([bg3]) })
      expect(await screen.findByText("Fast-installing Baldur's Gate 3 — 46% (downloading depot 3/8)")).toBeInTheDocument()
      expect(screen.getByRole('progressbar', { name: "Baldur's Gate 3 download" })).toHaveAttribute('aria-valuenow', '46')
      expect(screen.getByText('5m elapsed')).toBeInTheDocument()
    })

    it('shows the phase alone before a percent is known', async () => {
      show({ 'GET /api/daemon': daemon([{ ...bg3, phase: 'shutting Steam down', percent: null, elapsed_seconds: 12 }]) })
      expect(await screen.findByText("Fast-installing Baldur's Gate 3 — shutting Steam down")).toBeInTheDocument()
      expect(screen.getByRole('progressbar', { name: "Baldur's Gate 3 download" })).toHaveClass('bar-indeterminate')
    })

    it('keeps a failed daemon run on screen with its reason', async () => {
      const failed = { ...bg3, phase: 'failed', percent: null, elapsed_seconds: 0, error: 'Refusing to mark it as installed' }
      show({ 'GET /api/daemon': daemon([failed]) })
      expect((await screen.findByText("Fast install of Baldur's Gate 3 failed: Refusing to mark it as installed")).closest('p')).toHaveClass('text-danger')
      expect(screen.getByText("Steam's own download took over.")).toBeInTheDocument()
      expect(screen.queryByRole('progressbar', { name: "Baldur's Gate 3 download" })).not.toBeInTheDocument()
    })

    it('stays out of the way when nothing is installing', async () => {
      show({ 'GET /api/daemon': { ...daemon(), fast_installs: undefined } })
      expect(await screen.findByText('Hollow Knight')).toBeInTheDocument()
      expect(screen.queryByText(/Fast-installing/)).not.toBeInTheDocument()
      expect(screen.queryByRole('region', { name: 'Fast install' })).not.toBeInTheDocument()
    })
  })

  describe('gaming today', () => {
    it('shows time left and what is billing', async () => {
      show()
      expect(await screen.findByText(/left of 8h 0m/)).toBeInTheDocument()
      expect(screen.getByText('Now: Hollow Knight')).toBeInTheDocument()
      expect(screen.getByRole('progressbar', { name: 'Budget used' })).toHaveClass('bar-accent')
      expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute('href', '/gaming/')
    })

    it('says nothing is billing', async () => {
      show({ 'GET /api/budget': makeBudget({ session: { ...makeBudget().session, billing_label: '' } }) })
      expect(await screen.findByText('Now: nothing billing')).toBeInTheDocument()
    })

    it('warns when the day is almost used', async () => {
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
      expect(await screen.findByText('state file unreadable')).toHaveClass('text-danger')
    })

    it('has a default message too', async () => {
      show({ 'GET /api/budget': makeBudget({ today: null, error: null }) })
      expect(await screen.findByText('Budget state unavailable.')).toBeInTheDocument()
    })

    it('shows loading while the budget is in flight', async () => {
      show({ 'GET /api/budget': () => new Promise(() => undefined) })
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
      expect(screen.getByRole('link', { name: 'All jobs' })).toHaveAttribute('href', '/jobs/')
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
      const first = document.querySelector('a[href="/jobs/?id=a"]')
      expect(first).toHaveTextContent('Scan')
      expect(first?.querySelector('.pill')).toHaveAttribute('aria-label', 'succeeded')
      expect(screen.queryByText(/No jobs yet/)).not.toBeInTheDocument()
    })

    it('explains a failed load', async () => {
      show({ 'GET /api/jobs': apiError(500, 'op_failed', 'jobs broke') })
      expect(await screen.findByText('jobs broke')).toBeInTheDocument()
    })
  })
})
