import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { routes } from '../test/dialogRoutes'
import { makeSpec } from '../test/fixtures'
import { renderRouted, stubApi } from '../test/harness'
import { RunnerProvider } from './RunnerProvider'
import { useRunner } from './runnerContext'

function Launcher() {
  const { run, openPalette } = useRunner()
  return (
    <>
      <button type="button" onClick={() => run('scan')}>run scan</button>
      <button type="button" onClick={() => run('done', { n: 1 })}>run done</button>
      <button type="button" onClick={openPalette}>open palette</button>
    </>
  )
}

function mount() {
  stubApi(routes([makeSpec('scan'), makeSpec('done')]))
  return renderRouted(
    <RunnerProvider>
      <Launcher />
    </RunnerProvider>,
  )
}

describe('RunnerProvider', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens the runner dialog for a command, and closes it', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'run scan' }))
    expect(await screen.findByRole('dialog', { name: 'Scan' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('starts a fresh form each time the same command is run again', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'run done' }))
    expect(await screen.findByRole('dialog', { name: 'Done' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await userEvent.click(screen.getByRole('button', { name: 'run done' }))
    expect(await screen.findByRole('dialog', { name: 'Done' })).toBeInTheDocument()
  })

  it('opens the palette from a button and from Ctrl+K, which toggles it', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'open palette' }))
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
    await userEvent.keyboard('{Control>}k{/Control}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await userEvent.keyboard('{Meta>}K{/Meta}')
    expect(await screen.findByRole('dialog', { name: 'Command palette' })).toBeInTheDocument()
  })

  it('closes the palette from its own close button', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'open palette' }))
    await screen.findByRole('dialog', { name: 'Command palette' })
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('ignores a plain k, and Ctrl+K while a wide dialog owns the screen', async () => {
    mount()
    await screen.findByRole('button', { name: 'run scan' })
    await userEvent.keyboard('k')
    expect(screen.queryByRole('dialog')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'run scan' }))
    await screen.findByRole('dialog', { name: 'Scan' })
    await userEvent.keyboard('{Control>}k{/Control}')
    expect(screen.queryByRole('dialog', { name: 'Command palette' })).toBeNull()
    expect(screen.getByRole('dialog', { name: 'Scan' })).toBeInTheDocument()
  })

  it('running a command from the palette swaps the palette for the runner', async () => {
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'open palette' }))
    await userEvent.click(await screen.findByText('Does scan.'))
    expect(await screen.findByRole('dialog', { name: 'Scan' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Command palette' })).toBeNull()
  })

  it('stops listening for Ctrl+K when unmounted', async () => {
    const view = mount()
    await screen.findByRole('button', { name: 'run scan' })
    view.unmount()
    await userEvent.keyboard('{Control>}k{/Control}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
