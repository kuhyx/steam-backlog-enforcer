import { screen, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { CompatPayload } from '../api/contract'
import { q } from '../api/queries'
import { runner, type RunRequest } from '../lib/runner'
import { makeCompatRow, makeInstalled, makeLibGame, makeSpec } from '../test/fixtures'
import { apiError, flush, mount, stubApi, type Handler } from '../test/harness'
import '../sections/library'
import './compatTable'

const TOOL = 'proton-cachyos-native'
const payload = (rows = ROWS): CompatPayload => ({ tool: TOOL, tool_ready: true, rows })
const ROWS = [
  makeCompatRow({ app_id: 292030, name: 'The Witcher 3' }),
  makeCompatRow({ app_id: 70, name: 'Half-Life', decided: null, map: false, changes: false, reasons: ['native'] }),
  makeCompatRow({ app_id: 1091500, name: 'Cyberpunk 2077' }),
  makeCompatRow({ app_id: 413150, name: 'Stardew Valley', current: TOOL, priority: '250', changes: false, note: 'already mapped' }),
]

const at = (url: string) => {
  history.replaceState(null, '', url)
}
const region = () => screen.getByRole('region', { name: 'Proton map' })
const bodyNames = () => [...region().querySelectorAll('tbody tr')].map((tr) => tr.querySelector('td.name')?.textContent)
const applyBtn = () => screen.getByRole('button', { name: /^Map \d+ games$/ })

async function show(compat: Handler = payload()): Promise<RunRequest[]> {
  stubApi({ 'GET /api/compat': compat })
  mount('<compat-table></compat-table>')
  await screen.findByRole('region', { name: 'Proton map' })
  const seen: RunRequest[] = []
  runner.onRun((r) => seen.push(r))
  return seen
}

describe('<compat-table>', () => {
  afterEach(() => {
    at('/')
  })

  it('shows every game, the changing ones first, Valve default as an icon', async () => {
    await show()
    expect(bodyNames()).toEqual(['Cyberpunk 2077', 'The Witcher 3', 'Half-Life', 'Stardew Valley'])
    const halfLife = within(region()).getByRole('row', { name: /Half-Life/ })
    expect(within(halfLife).getAllByRole('img', { name: 'Valve default' })).toHaveLength(2)
    expect(halfLife).toHaveTextContent('native')
    expect(within(halfLife).getByRole('img', { name: 'Unchanged' })).toBeInTheDocument()
    expect(region()).toHaveTextContent(TOOL)
    expect(region().textContent).not.toMatch(/\[object Object\]|undefined|NaN/)
  })

  it('sorts on every header click, flips on the second, and keeps it in the hash', async () => {
    await show()
    const heads = [...region().querySelectorAll<HTMLTableCellElement>('thead th.clickable')]
    expect(heads).toHaveLength(6)
    for (const th of heads) {
      const before = bodyNames().join()
      await userEvent.click(th)
      const once = bodyNames().join()
      await userEvent.click(th)
      expect([once, bodyNames().join()].some((order) => order !== before)).toBe(true)
      expect(th).toHaveAttribute('aria-sort')
    }
    expect(location.hash).toContain('c.sort=changes')
  })

  it('restores sort, filters and search from the hash', async () => {
    at('/library/#view=compat&c.sort=name&c.dir=asc&c.q=wicher')
    await show()
    expect(bodyNames()).toEqual(['The Witcher 3'])
    expect(screen.getByRole('searchbox', { name: 'Search games' })).toHaveValue('wicher')
  })

  it('filters by a column select and by search', async () => {
    await show()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter Changes' }), 'same')
    expect(bodyNames()).toEqual(['Half-Life', 'Stardew Valley'])
    expect(location.hash).toContain('c.f.changes=same')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Filter Reason' }), 'already')
    expect(bodyNames()).toEqual(['Stardew Valley'])
  })

  it('maps every visible changing game when none is selected', async () => {
    const seen = await show()
    expect(applyBtn()).toHaveAccessibleName('Map 2 games')
    await userEvent.click(applyBtn())
    expect(seen).toEqual([{ name: 'map-installed', preset: { appids: '1091500,292030' } }])
  })

  it('maps only the selected games, and only changing rows can be selected', async () => {
    const seen = await show()
    expect(screen.queryByRole('checkbox', { name: 'Select Half-Life' })).toBeNull()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select The Witcher 3' }))
    await userEvent.click(screen.getByRole('button', { name: 'Map 1 games' }))
    expect(seen.at(-1)).toEqual({ name: 'map-installed', preset: { appids: '292030' } })
  })

  it('follows a hand-edited hash, clears a filter and narrows by app id range', async () => {
    await show()
    at('/library/#c.f.changes=same')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(bodyNames()).toEqual(['Half-Life', 'Stardew Valley'])
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Filter Changes' }), '')
    expect(bodyNames()).toHaveLength(4)
    expect(location.hash).not.toContain('c.f.changes')
    await userEvent.type(screen.getByRole('spinbutton', { name: 'App id min' }), '400000')
    expect(bodyNames()).toEqual(['Cyberpunk 2077', 'Stardew Valley'])
  })

  it('unticking the last selected game goes back to every changing game', async () => {
    await show()
    const box = screen.getByRole('checkbox', { name: 'Select The Witcher 3' })
    await userEvent.click(box)
    expect(applyBtn()).toHaveAccessibleName('Map 1 games')
    await userEvent.click(box)
    expect(applyBtn()).toHaveAccessibleName('Map 2 games')
  })

  it('cannot apply when nothing would change', async () => {
    await show(payload([ROWS[1], ROWS[3]]))
    expect(applyBtn()).toBeDisabled()
  })

  it('refreshes rows in place without losing the search text', async () => {
    const routes: Record<string, Handler> = { 'GET /api/compat': payload() }
    stubApi(routes)
    mount('<compat-table></compat-table>')
    await screen.findByRole('region', { name: 'Proton map' })
    const search = screen.getByRole('searchbox', { name: 'Search games' })
    await userEvent.type(search, 'cyber')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Cyberpunk 2077' }))
    routes['GET /api/compat'] = payload([makeCompatRow({ app_id: 1091500, name: 'Cyberpunk 2077', changes: false, note: 'already mapped', current: TOOL })])
    await q.compat.refetch()
    await flush()
    expect(screen.getByRole('searchbox', { name: 'Search games' })).toBe(search)
    expect(search).toHaveValue('cyber')
    expect(applyBtn()).toBeDisabled()
  })

  it('keeps a selected game that still changes after a refresh', async () => {
    const routes: Record<string, Handler> = { 'GET /api/compat': payload() }
    stubApi(routes)
    mount('<compat-table></compat-table>')
    await screen.findByRole('region', { name: 'Proton map' })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select The Witcher 3' }))
    await q.compat.refetch()
    await flush()
    expect(screen.getByRole('checkbox', { name: 'Select The Witcher 3' })).toBeChecked()
    expect(applyBtn()).toHaveAccessibleName('Map 1 games')
  })

  it('shows the server error', async () => {
    stubApi({ 'GET /api/compat': apiError(502, 'op_failed', 'no app cache') })
    mount('<compat-table></compat-table>')
    await flush(20)
    expect(document.body).toHaveTextContent('⛔')
  })
})

describe('library view switch', () => {
  afterEach(() => {
    at('/')
  })

  it('offers the Proton map as a third view, kept in the hash', async () => {
    at('/library/')
    stubApi({
      'GET /api/library': { games: [makeLibGame()] },
      'GET /api/installed': { games: [makeInstalled()] },
      'GET /api/commands': [makeSpec('map-installed')],
      'GET /api/compat': payload(),
    })
    mount('<library-view></library-view>')
    await userEvent.click(screen.getByRole('button', { name: 'Proton map' }))
    expect(location.hash).toContain('view=compat')
    expect(await screen.findByRole('region', { name: 'Proton map' })).toBeVisible()
  })
})
