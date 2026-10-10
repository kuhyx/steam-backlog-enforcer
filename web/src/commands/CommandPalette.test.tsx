import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, renderRouted, stubApi } from '../test/harness'
import { makeSpec } from '../test/fixtures'
import { CommandPalette } from './CommandPalette'

const SPECS = [
  makeSpec('scan', { description: 'Scan achievements.' }),
  makeSpec('unblock', { description: 'Open the store.', friction: { phrase_template: 'x' } }),
  makeSpec('status', { kind: 'view', description: 'Show status.' }),
  makeSpec('pick', { description: 'Pick next.', locked_reason: 'Locked by a pick' }),
]

function open() {
  const onClose = vi.fn()
  const onRun = vi.fn()
  const view = renderRouted(<CommandPalette onClose={onClose} onRun={onRun} />)
  return { onClose, onRun, ...view }
}
const box = () => screen.getByRole('combobox', { name: 'Search commands' })
const opt = (title: string) =>
  screen.getAllByRole('option').find((o) => o.querySelector('.palette-title')?.firstChild?.textContent === title)!
const active = () => screen.getAllByRole('option').findIndex((o) => o.getAttribute('aria-selected') === 'true')

describe('CommandPalette', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists every command, then the sections', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    open()
    expect(await screen.findByText('Scan achievements.')).toBeInTheDocument()
    expect(opt('Scan')).toHaveTextContent('run')
    expect(opt('Unblock')).toHaveTextContent('run · confirm')
    expect(opt('Status')).toHaveTextContent('open /')
    expect(opt('Pick')).toHaveTextContent('locked')
    expect(opt('Pick')).toHaveTextContent('Locked by a pick') // the reason replaces the description
    expect(screen.getByText('Go to Dashboard')).toBeInTheDocument()
    expect(box()).toHaveFocus()
  })

  it('shows loading and then an error', async () => {
    let fail: (r: unknown) => void = () => {}
    stubApi({ 'GET /api/commands': () => new Promise((r) => (fail = r)) })
    open()
    expect(await screen.findByText(/Loading commands/)).toBeInTheDocument()
    await act(async () => fail(apiError(500, 'op_failed', 'catalog broken')))
    expect(await screen.findByText('catalog broken')).toBeInTheDocument()
    expect(screen.queryByText(/Loading commands/)).toBeNull()
  })

  it('filters by text and says when nothing matches', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    open()
    await screen.findByText('Scan achievements.')
    await userEvent.type(box(), 'store')
    expect(screen.getAllByRole('option')).toHaveLength(2) // unblock + "Go to Store"
    await userEvent.clear(box())
    await userEvent.type(box(), 'zzz')
    expect(screen.getByText('No command matches “zzz”.')).toBeInTheDocument()
    expect(box()).not.toHaveAttribute('aria-activedescendant')
  })

  it('moves with arrows and pages, clamped, and announces the active option', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    open()
    await screen.findByText('Scan achievements.')
    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    expect(active()).toBe(2)
    expect(box().getAttribute('aria-activedescendant')).toBe(screen.getAllByRole('option')[2].id)
    await userEvent.keyboard('{ArrowUp}{ArrowUp}{ArrowUp}')
    expect(active()).toBe(0)
    await userEvent.keyboard('{PageDown}')
    expect(active()).toBe(8)
    await userEvent.keyboard('{PageDown}')
    expect(active()).toBe(11) // 4 commands + 8 sections - 1
    await userEvent.keyboard('{PageUp}')
    expect(active()).toBe(3)
    await userEvent.keyboard('{PageUp}')
    expect(active()).toBe(0)
  })

  it('the pointer moves the highlight too', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    open()
    await screen.findByText('Scan achievements.')
    await userEvent.hover(screen.getAllByRole('option')[1])
    expect(active()).toBe(1)
  })

  it('Enter runs a job command', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    const { onRun } = open()
    await screen.findByText('Scan achievements.')
    await userEvent.keyboard('{Enter}')
    expect(onRun).toHaveBeenCalledWith('scan')
  })

  it('Enter on a view command navigates and closes', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    const { onClose, onRun, router } = open()
    await screen.findByText('Scan achievements.')
    await userEvent.type(box(), 'show status')
    await userEvent.keyboard('{Enter}')
    expect(onRun).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
    expect(router.state.location.pathname).toBe('/')
  })

  it('clicking a section navigates', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    const { onClose, router } = open()
    await userEvent.click(await screen.findByText('Go to Jobs'))
    expect(onClose).toHaveBeenCalled()
    expect(router.state.location.pathname).toBe('/jobs')
  })

  it('Enter with nothing shown does nothing', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    const { onRun, onClose } = open()
    await screen.findByText('Scan achievements.')
    await userEvent.type(box(), 'zzz{Enter}')
    expect(onRun).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('ignores other keys', async () => {
    stubApi({ 'GET /api/commands': SPECS })
    const { onRun } = open()
    await screen.findByText('Scan achievements.')
    await userEvent.keyboard('{Tab}{Shift}')
    expect(onRun).not.toHaveBeenCalled()
  })
})
