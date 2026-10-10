import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { routes } from '../test/dialogRoutes'
import { makeJob, makeSpec } from '../test/fixtures'
import { apiError, bodiesOf, installEventSource, renderRouted, Reply, stubApi } from '../test/harness'
import { RunnerDialog } from './RunnerDialog'

function open(name: Parameters<typeof RunnerDialog>[0]['name'], preset?: Record<string, number | string>) {
  const onClose = vi.fn()
  const view = renderRouted(<RunnerDialog name={name} preset={preset} onClose={onClose} />)
  return { onClose, ...view }
}
const run = (label: string | RegExp) => screen.findByRole('button', { name: label })

describe('RunnerDialog', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('shows loading, then the load error', async () => {
    let fail: (r: unknown) => void = () => {}
    stubApi({ 'GET /api/commands': () => new Promise((r) => (fail = r)) })
    open('scan')
    expect(await screen.findByText(/Loading commands/)).toBeInTheDocument()
    await act(async () => fail(apiError(500, 'op_failed', 'catalog broken')))
    expect(await screen.findByText('catalog broken')).toBeInTheDocument()
  })

  it('says so when the server does not offer the command', async () => {
    stubApi(routes([makeSpec('done')]))
    open('scan')
    expect(await screen.findByText('Not in the server catalog')).toBeInTheDocument()
    expect(screen.getByText(/does not offer "scan"/)).toBeInTheDocument()
  })

  it('describes the command with its tags', async () => {
    stubApi(routes([makeSpec('enforce', { description: 'Enforce.', privileged: true, mutating: false, cancellable: true, friction: { phrase_template: 'x', countdown_seconds: 300 } })]))
    open('enforce')
    expect(await screen.findByText('Enforce.')).toBeInTheDocument()
    expect(screen.getByText('Runs as root via the daemon')).toBeInTheDocument()
    expect(screen.getByText('Read-only')).toBeInTheDocument()
    expect(screen.getByText('Cancellable')).toBeInTheDocument()
    expect(screen.getByText('5 min countdown')).toBeInTheDocument()
    expect(await run('Arm countdown')).toBeInTheDocument()
  })

  it('runs the enforce preset it was opened for, with no mode field to change it', async () => {
    const demo = { name: 'demo', label: 'Demo mode', type: 'int' as const, required: false, default: 0, min: 0, max: 1 }
    const mock = stubApi(routes([makeSpec('enforce', { kind: 'screen', params: [demo], privileged: true, cancellable: true })], { 'POST /api/jobs': makeJob({ id: 'j1' }) }))
    open('enforce', { demo: 1 })
    const button = await run('Run enforce')
    expect(screen.getByText('Cancellable')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Demo mode/)).toBeNull()
    expect(screen.queryByText('Runs as root via the daemon')).toBeNull()
    await userEvent.click(button)
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'enforce', params: { demo: 1 } }])
  })

  it('tags a state-changing command, with no countdown for an immediate one', async () => {
    stubApi(routes([makeSpec('scan', { friction: { phrase_template: 'x' } })]))
    open('scan')
    expect(await screen.findByText('Changes state')).toBeInTheDocument()
    expect(screen.queryByText(/countdown/)).toBeNull()
  })

  it('runs a parameterless command and follows its job', async () => {
    const mock = stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': makeJob({ id: 'j1' }) }))
    const { onClose, router } = open('scan')
    const button = await run('Run scan')
    expect(button).toHaveFocus()
    await userEvent.click(button)
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'scan', params: {} }])
    expect(await screen.findByRole('region', { name: 'Job Scan' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Open in Jobs' }))
    expect(router.state.location.pathname).toBe('/jobs/j1')
    await waitFor(() => expect(onClose).toHaveBeenCalled()) // navigating away closes it
  })

  it('"Close" leaves the job running', async () => {
    stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': makeJob({ id: 'j1' }) }))
    const { onClose } = open('scan')
    await userEvent.click(await run('Run scan'))
    await userEvent.click(await run('Close (job keeps running)'))
    expect(onClose).toHaveBeenCalled()
  })

  it('Cancel closes the form', async () => {
    stubApi(routes([makeSpec('scan')]))
    const { onClose } = open('scan')
    await userEvent.click(await run('Cancel'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  describe('parameters', () => {
    const spec = makeSpec('abandon-pick', {
      params: [{ name: 'app_id', label: 'Game', type: 'app_id', required: true }],
    })

    it('blocks an invalid submit and shows why', async () => {
      const mock = stubApi(routes([spec]))
      open('abandon-pick')
      // The button is disabled while invalid, so only a forced submit (e.g. a
      // script) reaches the validation display.
      expect(await run('Run abandon-pick')).toBeDisabled()
      fireEvent.submit(screen.getByRole('button', { name: 'Run abandon-pick' }).closest('form')!)
      expect(await screen.findByText('Game is required.')).toBeInTheDocument()
      expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([])
    })

    it('starts from a preset and sends typed values', async () => {
      const mock = stubApi(routes([spec], { 'POST /api/jobs': makeJob({ id: 'j1' }) }))
      open('abandon-pick', { app_id: 7 })
      expect(await screen.findByLabelText(/Game/)).toHaveValue('7')
      await waitFor(() => expect(document.querySelector('.field-help')).toHaveTextContent('Seven')) // useGameLookup
      await userEvent.click(await run('Run abandon-pick'))
      expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'abandon-pick', params: { app_id: 7 } }])
    })
  })

  it('shows a parameter that appears when the catalog refreshes under an open form', async () => {
    const alphaSpec = makeSpec('hide', { params: [{ name: 'a', label: 'Alpha', type: 'int', required: false }] })
    const table = routes([alphaSpec])
    stubApi(table)
    open('hide')
    await screen.findByLabelText('Alpha')
    table['GET /api/commands'] = [
      makeSpec('hide', {
        params: [
          { name: 'a', label: 'Alpha', type: 'int', required: false },
          { name: 'b', label: 'Beta', type: 'int', required: true },
        ],
      }),
    ]
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['commands'] })
    })
    expect(await screen.findByLabelText(/Beta/)).toHaveValue(null)
    expect(await run('Run hide')).toBeDisabled() // Beta is required and empty
  })

  describe('friction', () => {
    const spec = makeSpec('uninstall', {
      params: [{ name: 'app_id', label: 'Game', type: 'app_id', required: true }],
      friction: { phrase_template: 'uninstall {game_name} and {count} others' },
    })

    it('shows the exact phrase once its fields are known, and sends it', async () => {
      const mock = stubApi(routes([spec], { 'POST /api/jobs': makeJob({ id: 'j1' }) }))
      open('uninstall')
      expect(await screen.findByText(/Fill in the fields above to see the exact phrase \(game_name\)/)).toBeInTheDocument()
      await userEvent.type(screen.getByLabelText(/Game/), '7')
      const submit = await run('Run uninstall')
      expect(submit).toBeDisabled()
      expect(submit).toHaveClass('btn-danger')
      await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), 'uninstall Seven and 1 others')
      expect(submit).toBeEnabled()
      await userEvent.click(submit)
      expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([
        { command: 'uninstall', params: { app_id: 7 }, confirm_phrase: 'uninstall Seven and 1 others' },
      ])
    })

    it('focuses the phrase straight away when there are no fields', async () => {
      stubApi(routes([makeSpec('reset', { friction: { phrase_template: 'reset everything' } })]))
      open('reset')
      expect(await screen.findByLabelText('Type the phrase to confirm')).toHaveFocus()
    })

    it('does not submit a wrong phrase on Enter', async () => {
      const mock = stubApi(routes([makeSpec('reset', { friction: { phrase_template: 'reset everything' } })]))
      open('reset')
      await userEvent.type(await screen.findByLabelText('Type the phrase to confirm'), 'nope{Enter}')
      expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([])
    })
  })

  it('is read-only when locked, and explains', async () => {
    stubApi(routes([makeSpec('pick', { locked_reason: 'Manual pick active', friction: { phrase_template: 'x' }, params: [{ name: 'n', label: 'N', type: 'int', required: false }] })]))
    open('pick')
    expect(await screen.findByText('Manual pick active')).toBeInTheDocument()
    expect(screen.getByLabelText('N')).toBeDisabled()
    expect(screen.queryByLabelText('Type the phrase to confirm')).toBeNull()
    expect(await run('Run pick')).toBeDisabled()
  })

  describe('start failures', () => {
    it('shows the server error', async () => {
      stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': apiError(409, 'busy', 'job 4 running') }))
      open('scan')
      await userEvent.click(await run('Run scan'))
      expect(await screen.findByText('job 4 running')).toBeInTheDocument()
      expect(screen.queryByText(/terminal instead/)).toBeNull()
    })

    it('offers the sudo fallback when the daemon is down', async () => {
      stubApi(routes([makeSpec('gaming-unblock')], { 'POST /api/jobs': apiError(502, 'daemon_unreachable') }))
      open('gaming-unblock')
      await userEvent.click(await run('Run gaming-unblock'))
      expect(await screen.findByText('Run it from a terminal instead:')).toBeInTheDocument()
      expect(screen.getByText('sudo ./run.sh gaming-unblock')).toBeInTheDocument()
    })

    it('has no fallback for a command without one', async () => {
      stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': apiError(502, 'daemon_unreachable') }))
      open('scan')
      await userEvent.click(await run('Run scan'))
      expect(await screen.findByText('Root daemon unreachable')).toBeInTheDocument()
      expect(screen.queryByText(/terminal instead/)).toBeNull()
    })

    it('copes with a garbled reply', async () => {
      stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': new Reply(200, undefined, '{garbled') }))
      open('scan')
      await userEvent.click(await run('Run scan'))
      expect(await screen.findByText('Unexpected server error')).toBeInTheDocument()
    })

    it('shows Starting… while waiting', async () => {
      stubApi(routes([makeSpec('scan')], { 'POST /api/jobs': () => new Promise(() => {}) }))
      open('scan')
      await userEvent.click(await run('Run scan'))
      expect(await run('Starting…')).toBeDisabled()
    })
  })
})
