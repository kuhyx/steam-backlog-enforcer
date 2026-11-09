import { describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { makeJob, makeSpec } from '../test/fixtures'
import { button, setValue, submit } from '../test/events'
import { apiError, bodiesOf, stubApi } from '../test/harness'
import { field, found, openRunner, phraseInput, text } from '../test/runnerHelpers'
import { runner } from '../lib/runner'
import { RunnerDialogElement } from './runnerDialog'

const waitText = (s: string | RegExp) => vi.waitFor(() => {
  expect(text()).toMatch(s)
})

describe('<runner-dialog> catalog states', () => {
  it('shows loading, then the load error', async () => {
    let fail: (r: unknown) => void = () => undefined
    stubApi({ 'GET /api/commands': () => new Promise((r) => { fail = r }) })
    document.body.append(document.createElement('runner-dialog'))
    runner.run('scan')
    expect(text()).toContain('Loading commands')
    fail(apiError(500, 'op_failed', 'catalog broken'))
    await waitText('catalog broken')
  })

  it('says so when the server does not offer the command', async () => {
    openRunner([makeSpec('done')], 'scan')
    await waitText('Not in the server catalog')
    expect(text()).toContain('does not offer "scan"')
  })

  it('titles the dialog with the command label', async () => {
    const { el } = openRunner([makeSpec('pick-manual')], 'pick-manual')
    await found('Run pick-manual')
    expect(el.querySelector('dialog')).toHaveAttribute('aria-label', 'Pick manual')
    expect(el.querySelector('dialog')).toHaveAttribute('open')
  })
})

describe('<runner-dialog> form', () => {
  it('describes the command with its tags', async () => {
    openRunner(
      [makeSpec('enforce', { description: 'Enforce.', privileged: true, mutating: false, cancellable: true, friction: { phrase_template: 'x', countdown_seconds: 300 } })],
      'enforce',
    )
    await found('Arm countdown')
    for (const t of ['Enforce.', 'Runs as root via the daemon', 'Read-only', 'Cancellable', '5 min countdown']) expect(text()).toContain(t)
  })

  it('tags a state-changing command, with no countdown for an immediate one', async () => {
    openRunner([makeSpec('scan', { friction: { phrase_template: 'x' } })], 'scan')
    await waitText('Changes state')
    expect(text()).not.toMatch(/countdown/)
    expect(text()).not.toContain('Cancellable')
  })

  it('runs the enforce preset it was opened for, with no mode field to change it', async () => {
    const demo = { name: 'demo', label: 'Demo mode', type: 'int' as const, required: false, default: 0, min: 0, max: 1 }
    const spec = makeSpec('enforce', { kind: 'screen', params: [demo], privileged: true, cancellable: true })
    const { mock } = openRunner([spec], 'enforce', { preset: { demo: 1 }, extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    const run = await found('Run enforce')
    expect(text()).toContain('Cancellable')
    expect(text()).not.toContain('Demo mode')
    expect(text()).not.toContain('Runs as root via the daemon')
    submit(run)
    await vi.waitFor(() => { expect(bodiesOf(mock, 'POST /api/jobs')).toHaveLength(1) })
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'enforce', params: { demo: 1 } }])
  })

  it('runs a parameterless command and follows its job', async () => {
    const { mock, el } = openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    const run = await found('Run scan')
    expect(run).toHaveAttribute('autofocus')
    expect(run.className).toBe('btn btn-primary')
    submit(run)
    await found('Close (job keeps running)')
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'scan', params: {} }])
    expect(el.querySelector('job-progress')).toHaveAttribute('job-id', 'j1')
    expect(el.querySelector('a')).toHaveAttribute('href', '/jobs/?id=j1')
  })

  it('"Close" leaves the job running, and Cancel closes the form', async () => {
    const { el } = openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    submit(await found('Run scan'))
    ;(await found('Close (job keeps running)')).click()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
    runner.run('scan')
    ;(await found('Cancel')).click()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
  })

  it('ignores a catalog refresh under an open form', async () => {
    const { el } = openRunner([makeSpec('scan')], 'scan')
    await found('Run scan')
    const form = el.querySelector('form')
    q.commands.invalidate()
    await vi.waitFor(() => { expect(q.commands.state.loading).toBe(false) })
    expect(el.querySelector('form')).toBe(form)
  })

  it('re-opening replaces the previous request', async () => {
    const { el } = openRunner([makeSpec('scan'), makeSpec('done')], 'scan')
    await found('Run scan')
    runner.run('done')
    await found('Run done')
    expect(el.querySelector('dialog')).toHaveAttribute('aria-label', 'Done')
    expect((el as RunnerDialogElement).querySelectorAll('form')).toHaveLength(1)
  })
})

describe('<runner-dialog> parameters', () => {
  const spec = makeSpec('abandon-pick', { params: [{ name: 'app_id', label: 'Game', type: 'app_id', required: true }] })

  it('blocks an invalid submit and shows why', async () => {
    const { mock } = openRunner([spec], 'abandon-pick')
    const run = await found('Run abandon-pick')
    expect(run).toBeDisabled()
    submit(run)
    await waitText('Game is required.')
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([])
  })

  it('starts from a preset, names the game, and sends typed values', async () => {
    const { mock } = openRunner([spec], 'abandon-pick', { preset: { app_id: 7 }, extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    const run = await found('Run abandon-pick')
    expect(field(/Game/)).toHaveValue('7')
    await vi.waitFor(() => { expect(document.querySelector('.field-help')).toHaveTextContent('Seven') })
    expect(run).toBeEnabled()
    submit(run)
    await vi.waitFor(() => { expect(bodiesOf(mock, 'POST /api/jobs')).toHaveLength(1) })
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([{ command: 'abandon-pick', params: { app_id: 7 } }])
  })

  it('does not refresh the game names once the form is gone', async () => {
    openRunner([spec], 'abandon-pick', { preset: { app_id: 7 }, extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    submit(await found('Run abandon-pick'))
    await found('Close (job keeps running)')
    q.dataset.invalidate()
    await vi.waitFor(() => { expect(q.dataset.state.loading).toBe(false) })
    expect(text()).toContain('Open in Jobs')
  })
})

describe('<runner-dialog> friction', () => {
  const spec = makeSpec('uninstall', {
    params: [{ name: 'app_id', label: 'Game', type: 'app_id', required: true }],
    friction: { phrase_template: 'uninstall {game_name} and {count} others' },
  })

  it('shows the exact phrase once its fields are known, and sends it', async () => {
    const { mock } = openRunner([spec], 'uninstall', { extra: { 'POST /api/jobs': makeJob({ id: 'j1' }) } })
    const run = await found('Run uninstall')
    expect(text()).toMatch(/Fill in the fields above to see the exact phrase \(game_name\)/)
    setValue(field(/Game/), '7')
    await vi.waitFor(() => { expect(phraseInput()).toBeInTheDocument() })
    expect(run).toBeDisabled()
    expect(run).toHaveClass('btn-danger')
    setValue(phraseInput(), 'uninstall Seven and 1 others')
    expect(run).toBeEnabled()
    submit(run)
    await vi.waitFor(() => { expect(bodiesOf(mock, 'POST /api/jobs')).toHaveLength(1) })
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([
      { command: 'uninstall', params: { app_id: 7 }, confirm_phrase: 'uninstall Seven and 1 others' },
    ])
  })

  it('keeps the typed phrase while unrelated fields refresh, and resets it when the sentence changes', async () => {
    openRunner([spec], 'uninstall', { preset: { app_id: 7 } })
    await vi.waitFor(() => { expect(phraseInput()).toBeInTheDocument() })
    const input = phraseInput()
    setValue(input, 'uninst')
    q.status.invalidate()
    await vi.waitFor(() => { expect(q.status.state.loading).toBe(false) })
    expect(phraseInput()).toBe(input)
    expect(input).toHaveValue('uninst')
    setValue(field(/Game/), '8')
    await vi.waitFor(() => { expect(phraseInput()).toHaveValue('') })
  })

  it('focuses the phrase straight away when there are no fields', async () => {
    openRunner([makeSpec('reset', { friction: { phrase_template: 'reset everything' } })], 'reset')
    await vi.waitFor(() => { expect(phraseInput()).toHaveAttribute('autofocus') })
  })

  it('does not submit a wrong phrase on Enter', async () => {
    const { mock } = openRunner([makeSpec('reset', { friction: { phrase_template: 'reset everything' } })], 'reset')
    await vi.waitFor(() => { expect(phraseInput()).toBeInTheDocument() })
    setValue(phraseInput(), 'nope')
    submit(phraseInput())
    expect(bodiesOf(mock, 'POST /api/jobs')).toEqual([])
    expect(button(document.body, 'Run reset')).toBeDisabled()
  })
})
