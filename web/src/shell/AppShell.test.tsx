import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSpec } from '../test/fixtures'
import { renderRouted, stubApi } from '../test/harness'
import { AppShell } from './AppShell'
import { NAV } from './nav'

const ROUTES = {
  'GET /api/setup': { configured: true, has_api_key: true, steam_id: '7656119800000000' },
  'GET /api/server': { stale: false, started_at: 't', version: '1' },
  'GET /api/daemon': { state: 'running', started_at: null, pid: 1, journal_tail: [], restart_available_at: null },
  'GET /api/jobs': [],
  'GET /api/commands': [makeSpec('scan')],
}

describe('AppShell', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('has a skip link, the sections, the top bar and a main landmark', async () => {
    stubApi(ROUTES)
    renderRouted(<AppShell />)
    expect(await screen.findByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main')
    const nav = screen.getByRole('navigation', { name: 'Sections' })
    expect(nav.querySelectorAll('a')).toHaveLength(NAV.length)
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main')
    expect(screen.getByRole('button', { name: /Commands/ })).toHaveAttribute('aria-keyshortcuts', 'Control+K')
    expect(await screen.findByText('Server ok')).toBeInTheDocument()
  })

  it('marks the current section', async () => {
    stubApi(ROUTES)
    renderRouted(<AppShell />, '/gaming')
    const link = await screen.findByRole('link', { name: /Gaming/ })
    expect(link).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: /Dashboard/ })).not.toHaveAttribute('aria-current')
  })

  it('opens the palette from the top bar', async () => {
    stubApi(ROUTES)
    renderRouted(<AppShell />)
    await userEvent.click(await screen.findByRole('button', { name: /Commands/ }))
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
  })

  it('sends an unconfigured install to Setup, and lets Setup itself render', async () => {
    stubApi({ ...ROUTES, 'GET /api/setup': { configured: false, has_api_key: false, steam_id: null } })
    const { router } = renderRouted(<AppShell />, '/library')
    await waitFor(() => expect(router.state.location.pathname).toBe('/setup'))
    expect(await screen.findByRole('navigation', { name: 'Sections' })).toBeInTheDocument()
  })

  describe('Alt+digit', () => {
    const go = async (keys: string, at = '/') => {
      stubApi(ROUTES)
      const view = renderRouted(<AppShell />, at)
      await screen.findByRole('navigation', { name: 'Sections' })
      await userEvent.keyboard(keys)
      return view.router
    }

    it('jumps to the numbered section', async () => {
      const router = await go('{Alt>}3{/Alt}')
      await waitFor(() => expect(router.state.location.pathname).toBe('/picks'))
    })

    it('ignores a digit without Alt, with Ctrl or Meta, and unknown digits', async () => {
      const router = await go('3{Alt>}9{/Alt}{Control>}{Alt>}2{/Alt}{/Control}{Meta>}{Alt>}2{/Alt}{/Meta}')
      expect(router.state.location.pathname).toBe('/')
    })

    it('does nothing while a dialog is open', async () => {
      const router = await go('{Control>}k{/Control}')
      await screen.findByRole('dialog', { name: 'Command palette' })
      await userEvent.keyboard('{Alt>}2{/Alt}')
      await act(async () => {})
      expect(router.state.location.pathname).toBe('/')
    })
  })
})
