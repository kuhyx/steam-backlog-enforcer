import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CommandSpec } from '../api/contract'
import { q } from '../api/queries'
import { runner } from '../lib/runner'
import { makeSpec } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import { commandButton } from './commandButton'
import { must } from '../test/events'

const loaded = (specs: CommandSpec[]) => {
  stubApi({ 'GET /api/commands': specs })
}
const requests: unknown[] = []
let off = (): void => undefined

beforeEach(() => {
  off = runner.onRun((r) => requests.push(r))
})
afterEach(() => {
  off()
  requests.length = 0
})

describe('<command-button>', () => {
  it('runs a job command with its preset when clicked', async () => {
    loaded([makeSpec('scan')])
    const el = mount(`<command-button name="scan" preset='{"app_id":4}'></command-button>`)
    await vi.waitFor(() => {
      expect(el.querySelector('button')).toHaveAttribute('aria-label', 'Run scan')
    })
    const btn = must(el.querySelector('button'))
    expect(btn).toHaveAttribute('aria-disabled', 'false')
    expect(btn.className).toBe('btn btn-ghost')
    btn.click()
    expect(requests).toEqual([{ name: 'scan', preset: { app_id: 4 } }])
  })

  it('is inert until the catalog has loaded', async () => {
    loaded([])
    const el = mount('<command-button></command-button>')
    const btn = must(el.querySelector('button'))
    expect(btn).toHaveAttribute('aria-label', 'Open Status')
    expect(btn).toHaveAttribute('aria-disabled', 'true')
    btn.click()
    await vi.waitFor(() => {
      expect(q.commands.state.loading).toBe(false)
    })
    expect(requests).toEqual([])
  })

  it('stays focusable but inert while locked, and says why', async () => {
    loaded([makeSpec('pick', { locked_reason: 'Locked by a manual pick' })])
    const el = mount('<command-button name="pick" label="Pick it" tone="danger"></command-button>')
    const btn = must(el.querySelector('button'))
    expect(btn).toHaveAttribute('aria-label', 'Pick it')
    expect(btn.querySelector('.cmd-lock')).toBeNull()
    await vi.waitFor(() => {
      expect(el.querySelector('button')).toHaveAttribute('aria-description', 'Locked by a manual pick')
    })
    expect(el.querySelector('.cmd-lock')).not.toBeNull()
    expect(el.querySelector('button')).toHaveAttribute('aria-disabled', 'true')
    expect(el.querySelector('button')).toHaveClass('btn-danger')
    el.querySelector('button')?.click()
    expect(requests).toEqual([])
  })

  it('links to the owning page for a non-job command', async () => {
    loaded([makeSpec('status', { kind: 'view' })])
    const el = mount('<command-button name="status" tone="primary"></command-button>')
    await vi.waitFor(() => {
      expect(el.querySelector('a')).not.toBeNull()
    })
    const link = must(el.querySelector('a'))
    expect(link).toHaveAttribute('aria-label', 'Open Status')
    expect(link).toHaveAttribute('href', '/')
    expect(link).toHaveClass('btn-primary')
  })

  it('runs without a preset when the attribute is absent', async () => {
    loaded([makeSpec('scan')])
    const el = mount('<command-button name="scan"></command-button>')
    await vi.waitFor(() => {
      expect(el.querySelector('button')).toHaveAttribute('aria-label', 'Run scan')
    })
    el.querySelector('button')?.click()
    expect(requests).toEqual([{ name: 'scan' }])
  })
})

describe('commandButton()', () => {
  it('defaults to the ghost tone', () => {
    expect(commandButton({ name: 'scan' }).className).toBe('btn btn-ghost')
  })
})

describe('<command-card>', () => {
  it('shows the label, server description and a run button', async () => {
    loaded([makeSpec('scan', { description: 'Scans achievements.' })])
    const el = mount(`<command-card name="scan" preset='{"app_id":4}'></command-card>`)
    await vi.waitFor(() => {
      expect(el).toHaveTextContent('Scans achievements.')
    })
    expect(el.querySelector('h3')).toHaveTextContent('Scan')
    el.querySelector('button')?.click()
    expect(requests).toEqual([{ name: 'scan', preset: { app_id: 4 } }])
    expect(el.querySelector('article')).toHaveClass('cmd-card')
    expect(el.querySelector('article')).not.toHaveClass('locked')
  })

  it('marks privileged and countdown commands', async () => {
    loaded([makeSpec('gaming-reset', { privileged: true, friction: { phrase_template: 'x', countdown_seconds: 300 } })])
    const el = mount('<command-card name="gaming-reset"></command-card>')
    await vi.waitFor(() => {
      expect(el.querySelector('[aria-label="root"]')).not.toBeNull()
    })
    expect(el.querySelector('[aria-label="countdown"]')).not.toBeNull()
  })

  it('shows no countdown pill for a friction command without one', async () => {
    loaded([makeSpec('unblock', { friction: { phrase_template: 'x' } })])
    const el = mount('<command-card name="unblock"></command-card>')
    await vi.waitFor(() => {
      expect(el).toHaveTextContent('Does unblock.')
    })
    expect(el).not.toHaveTextContent('countdown')
    expect(el).not.toHaveTextContent('root')
  })

  it('shows the lock reason in place of the description', async () => {
    loaded([makeSpec('pick', { locked_reason: 'Locked by a manual pick' })])
    const el = mount('<command-card name="pick"></command-card>')
    await vi.waitFor(() => {
      expect(el.querySelector('.cmd-desc')).toHaveTextContent('Locked by a manual pick')
    })
    expect(el.querySelector('article')).toHaveClass('locked')
    expect(el.querySelector('button')).toHaveAttribute('aria-disabled', 'true')
  })

  it('shows a placeholder until the catalog has loaded', () => {
    loaded([])
    const el = mount('<command-card name="scan"></command-card>')
    expect(el.querySelector('.cmd-desc')).toHaveTextContent('…')
    expect(el.querySelector('button')).toHaveAttribute('aria-disabled', 'true')
  })
})
