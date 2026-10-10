import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeInstalled, makeLibGame, makeSpec } from '../test/fixtures'
import { apiError, renderRouted, stubApi } from '../test/harness'
import { Library } from './Library'

const routes = (installed: unknown = { games: [] }) => ({
  'GET /api/library': { games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' })] },
  'GET /api/installed': installed,
  'GET /api/commands': [makeSpec('install'), makeSpec('uninstall'), makeSpec('hide'), makeSpec('unhide')],
})

describe('Library', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens on the cover grid, with the install actions above', async () => {
    stubApi(routes())
    renderRouted(<Library />)
    expect(await screen.findByText('1 of 1 games')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All games' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Installed' })).toHaveAttribute('aria-pressed', 'false')
    for (const label of ['Install assigned', 'Hide others', 'Unhide all']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('counts what an uninstall would remove', async () => {
    stubApi(routes({
      games: [
        makeInstalled({ app_id: 1 }),
        makeInstalled({ app_id: 2, assigned: true }),
        makeInstalled({ app_id: 3, protected: true }),
        makeInstalled({ app_id: 4 }),
      ],
    }))
    renderRouted(<Library />)
    expect((await screen.findAllByText('Uninstall 2…')).length).toBeGreaterThan(0)
  })

  it('switches to the installed table and back', async () => {
    stubApi(routes({
      games: [
        makeInstalled({ app_id: 1, name: 'Assigned One', assigned: true, size_bytes: 2 * 1024 ** 3 }),
        makeInstalled({ app_id: 2, name: 'Proton', protected: true }),
        makeInstalled({ app_id: 3, name: 'Spare', size_bytes: 1024 ** 2 }),
      ],
    }))
    renderRouted(<Library />)
    await screen.findByText('1 of 1 games')
    await userEvent.click(screen.getByRole('button', { name: 'Installed' }))
    expect(await screen.findByRole('region', { name: 'Installed games' })).toBeInTheDocument()
    expect(screen.getByText(/3 games · 3\.0 GB/)).toBeInTheDocument() // 2 GB + 1 GB + 1 MB
    expect(screen.getByText('assigned')).toBeInTheDocument()
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(screen.getByText('uninstall candidate')).toBeInTheDocument()
    expect(screen.queryByText('1 of 1 games')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'All games' }))
    expect(await screen.findByText('1 of 1 games')).toBeInTheDocument()
  })

  it('says when nothing is installed', async () => {
    stubApi(routes())
    renderRouted(<Library />)
    await screen.findByText('1 of 1 games')
    await userEvent.click(screen.getByRole('button', { name: 'Installed' }))
    expect(await screen.findByText('No games installed.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('shows loading, then a failure, for the installed table', async () => {
    const table = routes(() => new Promise(() => {}))
    stubApi(table)
    renderRouted(<Library />)
    await screen.findByText('1 of 1 games')
    await userEvent.click(screen.getByRole('button', { name: 'Installed' }))
    expect(await screen.findByText(/Loading installed games/)).toBeInTheDocument()
  })

  it('explains a failed installed load', async () => {
    stubApi(routes(apiError(500, 'op_failed', 'installed broke')))
    renderRouted(<Library />)
    await screen.findByText('1 of 1 games')
    await userEvent.click(screen.getByRole('button', { name: 'Installed' }))
    expect(await screen.findByText('installed broke')).toBeInTheDocument()
  })
})
