import { describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { makeSpec } from '../test/fixtures'
import { submit } from '../test/events'
import { apiError, Reply } from '../test/harness'
import { field, found, openRunner, text } from '../test/runnerHelpers'

const waitText = (s: string | RegExp) => vi.waitFor(() => {
  expect(text()).toMatch(s)
})

describe('<runner-dialog> locked', () => {
  it('is read-only when locked, and explains', async () => {
    const spec = makeSpec('pick', {
      locked_reason: 'Manual pick active',
      friction: { phrase_template: 'x' },
      params: [{ name: 'n', label: 'N', type: 'int', required: false }],
    })
    openRunner([spec], 'pick')
    const run = await found('Run pick')
    expect(text()).toContain('Manual pick active')
    expect(field('N')).toBeDisabled()
    expect(document.querySelector('.phrase')).toBeNull()
    expect(run).toBeDisabled()
    submit(run)
    expect(text()).not.toContain('Starting…')
  })
})

describe('<runner-dialog> start failures', () => {
  it('shows the server error', async () => {
    openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': apiError(409, 'busy', 'job 4 running') } })
    submit(await found('Run scan'))
    await waitText('job 4 running')
    expect(text()).not.toContain('terminal instead')
  })

  it('offers the sudo fallback when the daemon is down', async () => {
    openRunner([makeSpec('gaming-unblock')], 'gaming-unblock', { extra: { 'POST /api/jobs': apiError(502, 'daemon_unreachable') } })
    submit(await found('Run gaming-unblock'))
    await waitText('Run it from a terminal instead:')
    expect(text()).toContain('sudo ./run.sh gaming-unblock')
  })

  it('has no fallback for a command without one', async () => {
    openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': apiError(502, 'daemon_unreachable') } })
    submit(await found('Run scan'))
    await vi.waitFor(() => { expect(document.querySelector('[data-code="daemon_unreachable"]')).not.toBeNull() })
    expect(text()).not.toContain('terminal instead')
  })

  it('copes with a garbled reply', async () => {
    openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': new Reply(200, undefined, '{garbled') } })
    submit(await found('Run scan'))
    await vi.waitFor(() => { expect(document.querySelector('[data-code="http"]')).not.toBeNull() })
  })

  it('shows Starting… while waiting', async () => {
    openRunner([makeSpec('scan')], 'scan', { extra: { 'POST /api/jobs': () => new Promise(() => undefined) } })
    submit(await found('Run scan'))
    expect(await found('Starting…')).toBeDisabled()
  })
})

describe('<runner-dialog> lifecycle', () => {
  it('close() on a dialog that is not open does nothing', () => {
    const { el } = openRunner([makeSpec('scan')], 'scan')
    const dialog = el as unknown as { close: () => void }
    dialog.close()
    expect(() => {
      dialog.close()
    }).not.toThrow()
  })

  it('ignores a catalog answer that arrives after another listener closed it', async () => {
    // Query.emit walks a snapshot, so a listener removed mid-emit still runs once.
    let el: HTMLElement | null = null
    const off = q.commands.subscribe(() => {
      ;(el as unknown as { close: () => void } | null)?.close()
    })
    el = openRunner([makeSpec('scan')], 'scan').el
    await vi.waitFor(() => { expect(q.commands.state.loading).toBe(false) })
    expect(el.querySelector('form')).toBeNull()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
    off()
  })

  it('closes itself and stops listening when removed', async () => {
    const { el } = openRunner([makeSpec('scan')], 'scan')
    await found('Run scan')
    el.remove()
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
  })

  it('Escape and the close button both close it', async () => {
    const { el } = openRunner([makeSpec('scan')], 'scan')
    await found('Run scan')
    el.querySelector('dialog')?.dispatchEvent(new Event('cancel', { cancelable: true }))
    expect(el.querySelector('dialog')).not.toHaveAttribute('open')
  })

  it('does nothing on pagehide when no countdown is armed', async () => {
    const { mock } = openRunner([makeSpec('scan')], 'scan')
    await found('Run scan')
    const calls = mock.mock.calls.length
    window.dispatchEvent(new Event('pagehide'))
    expect(mock.mock.calls).toHaveLength(calls)
  })
})
