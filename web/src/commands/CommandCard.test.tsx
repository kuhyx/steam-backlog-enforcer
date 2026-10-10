import { renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSpec } from '../test/fixtures'
import { renderRouted, stubApi } from '../test/harness'
import { CommandButton, CommandCard } from './CommandCard'
import { RunnerContext, useRunner } from './runnerContext'

const run = vi.fn()
const withRunner = (ui: React.ReactNode) => (
  <RunnerContext.Provider value={{ run, openPalette: () => {} }}>{ui}</RunnerContext.Provider>
)

describe('CommandCard', () => {
  afterEach(() => {
    run.mockClear()
    vi.unstubAllGlobals()
  })

  it('shows the label, server description and a run button', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('scan', { description: 'Scans achievements.' })] })
    renderRouted(withRunner(<CommandCard name="scan" preset={{ app_id: 4 }} />))
    expect(await screen.findByText('Scans achievements.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Scan' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Run scan' }))
    expect(run).toHaveBeenCalledWith('scan', { app_id: 4 })
  })

  it('marks privileged and countdown commands', async () => {
    stubApi({
      'GET /api/commands': [
        makeSpec('gaming-reset', {
          privileged: true,
          friction: { phrase_template: 'x', countdown_seconds: 300 },
        }),
      ],
    })
    renderRouted(withRunner(<CommandCard name="gaming-reset" />))
    expect(await screen.findByText('root')).toBeInTheDocument()
    expect(screen.getByText('countdown')).toBeInTheDocument()
  })

  it('shows no countdown pill for a friction command without one', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('unblock', { friction: { phrase_template: 'x' } })] })
    renderRouted(withRunner(<CommandCard name="unblock" />))
    await screen.findByText('Does unblock.')
    expect(screen.queryByText('countdown')).toBeNull()
  })

  it('stays focusable but inert while locked, and says why', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('pick', { locked_reason: 'Locked by a manual pick' })] })
    renderRouted(withRunner(<CommandCard name="pick" />))
    const button = await screen.findByRole('button', { name: 'Run pick' })
    expect(screen.getByText('Locked by a manual pick', { selector: '.cmd-desc' })).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAttribute('title', 'Locked by a manual pick')
    expect(document.querySelector('article')).toHaveClass('locked')
    await userEvent.click(button)
    expect(run).not.toHaveBeenCalled()
  })

  it('is inert until the catalog has loaded', async () => {
    stubApi({ 'GET /api/commands': [] })
    renderRouted(withRunner(<CommandCard name="scan" />))
    const button = await screen.findByRole('button', { name: 'Open Scan' })
    expect(screen.getByText('…')).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(button)
    expect(run).not.toHaveBeenCalled()
  })

  it('links to the owning screen for a non-job command', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('status', { kind: 'view' })] })
    const { router } = renderRouted(withRunner(<CommandButton name="status" tone="primary" />))
    const link = await screen.findByRole('link', { name: 'Open Status' })
    expect(link).toHaveClass('btn-primary')
    await userEvent.click(link)
    expect(router.state.location.pathname).toBe('/')
  })

  it('uses the given label and tone', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('scan')] })
    renderRouted(withRunner(<CommandButton name="scan" label="Scan now" tone="danger" />))
    expect(await screen.findByRole('button', { name: 'Scan now' })).toHaveClass('btn-danger')
  })
})

describe('runner context', () => {
  it('defaults to no-ops without a provider', () => {
    const { result } = renderHook(() => useRunner())
    expect(result.current.run('scan')).toBeUndefined()
    expect(result.current.openPalette()).toBeUndefined()
  })
})
