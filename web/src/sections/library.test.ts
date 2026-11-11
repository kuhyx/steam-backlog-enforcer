import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { q } from '../api/queries'
import '../commands/commandButton'
import { makeInstalled, makeLibGame, makeSpec } from '../test/fixtures'
import { apiError, mount, stubApi, type Handler } from '../test/harness'
import './library'

const routes = (installed: Handler = { games: [] }) => ({
  'GET /api/library': { games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' })] },
  'GET /api/installed': installed,
  'GET /api/commands': [makeSpec('install'), makeSpec('uninstall'), makeSpec('hide'), makeSpec('unhide')],
})

const at = (url: string) => {
  history.replaceState(null, '', url)
}
const PAGE = '<div><uninstall-card></uninstall-card><library-view></library-view></div>'
const viewBtn = (name: string) => screen.getByRole('button', { name })
const table = () => screen.queryByRole('region', { name: 'Installed games' })

describe('Library page', () => {
  afterEach(() => {
    at('/')
  })

  it('opens on the cover grid, with the browser keeping its state in the hash', async () => {
    at('/library/')
    stubApi(routes())
    mount(PAGE)
    expect(await screen.findByText('1 of 1 games')).toBeInTheDocument()
    expect(viewBtn('All games')).toHaveAttribute('aria-pressed', 'true')
    expect(viewBtn('Installed')).toHaveAttribute('aria-pressed', 'false')
    expect(document.querySelector('game-browser')).toHaveAttribute('hash-state')
    expect(screen.getByRole('group', { name: 'Games' }).closest('div[hidden]')).toBeNull()
  })

  it('counts what an uninstall would remove', async () => {
    stubApi(
      routes({
        games: [
          makeInstalled({ app_id: 1 }),
          makeInstalled({ app_id: 2, assigned: true }),
          makeInstalled({ app_id: 3, protected: true }),
          makeInstalled({ app_id: 4 }),
        ],
      }),
    )
    mount(PAGE)
    const btn = await screen.findByRole('button', { name: 'Uninstall 2…' })
    expect(btn.closest('command-card')).toHaveAttribute('name', 'uninstall')
  })

  it('rebuilds the uninstall card only when its count changes', async () => {
    const r: Record<string, Handler> = routes({ games: [makeInstalled({ app_id: 1 })] })
    stubApi(r)
    mount(PAGE)
    await screen.findByRole('button', { name: 'Uninstall 1…' })
    const cardEl = document.querySelector('uninstall-card command-card')
    await q.installed.refetch()
    expect(document.querySelector('uninstall-card command-card')).toBe(cardEl)
    r['GET /api/installed'] = { games: [] }
    q.installed.invalidate()
    await screen.findByRole('button', { name: 'Uninstall 0…' })
  })

  it('switches to the installed table and back, keeping the search', async () => {
    at('/library/')
    stubApi(
      routes({
        games: [
          makeInstalled({ app_id: 1, name: 'Assigned One', assigned: true, size_bytes: 2 * 1024 ** 3 }),
          makeInstalled({ app_id: 2, name: 'Proton', protected: true }),
          makeInstalled({ app_id: 3, name: 'Spare', size_bytes: 1024 ** 2 }),
        ],
      }),
    )
    mount(PAGE)
    await screen.findByText('1 of 1 games')
    await userEvent.type(screen.getByRole('combobox', { name: 'Search your games' }), 'hollow')
    await userEvent.click(viewBtn('Installed'))
    expect(location.hash).toBe('#q=hollow&view=installed')
    expect(viewBtn('Installed')).toHaveAttribute('aria-pressed', 'true')
    expect(table()).toBeInTheDocument()
    expect(table()?.closest('div[hidden]')).toBeNull()
    expect(screen.getByText(/3 games · 3\.0 GB/)).toBeInTheDocument() // 2 GB + 1 GB + 1 MB
    expect(screen.getByText('assigned')).toBeInTheDocument()
    expect(screen.getByText('protected')).toBeInTheDocument()
    expect(screen.getByText('uninstall candidate')).toBeInTheDocument()
    expect(document.querySelector('game-browser')?.closest('div[hidden]')).not.toBeNull()
    await userEvent.click(viewBtn('All games'))
    expect(location.hash).toBe('#q=hollow')
    expect(document.querySelector('game-browser')?.closest('div[hidden]')).toBeNull()
    expect(screen.getByRole('combobox', { name: 'Search your games' })).toHaveValue('hollow')
  })

  it('restores the view from the hash, and follows hash edits until detached', async () => {
    at('/library/#view=installed')
    stubApi(routes({ games: [makeInstalled({ name: 'Spare' })] }))
    const page = mount(PAGE)
    expect(await screen.findByText('Spare')).toBeInTheDocument()
    expect(viewBtn('Installed')).toHaveAttribute('aria-pressed', 'true')
    at('/library/')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(viewBtn('All games')).toHaveAttribute('aria-pressed', 'true')
    const view = page.getElementsByTagName('library-view')[0]
    view.remove()
    at('/library/#view=installed')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(view.querySelector('[aria-pressed="true"]')).toHaveAttribute('aria-label', 'All games')
    page.append(view) // re-attached: same controls, view re-read from the hash
    expect(view.querySelectorAll('.seg')).toHaveLength(1)
    expect(view.querySelector('[aria-pressed="true"]')).toHaveAttribute('aria-label', 'Installed')
  })

  it('says when nothing is installed', async () => {
    at('/library/#view=installed')
    stubApi(routes())
    mount(PAGE)
    expect(await screen.findByText('No games installed.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('shows loading for the installed table', async () => {
    at('/library/#view=installed')
    stubApi(routes(() => new Promise(() => undefined)))
    mount(PAGE)
    expect(await screen.findByText(/Loading installed games/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Uninstall 0…' })).toBeInTheDocument()
  })

  it('explains a failed installed load', async () => {
    at('/library/#view=installed')
    stubApi(routes(apiError(500, 'op_failed', 'installed broke')))
    mount(PAGE)
    expect(await screen.findByText('installed broke')).toBeInTheDocument()
    expect(screen.queryByText(/Loading installed/)).toBeNull()
  })
})
