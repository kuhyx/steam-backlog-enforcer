// Guard test (textgate-rework R6): the System and Setup pages paint glyphs,
// numbers, ids, dates and the daemon's own journal, never chrome words.

import { screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { makeSpec } from '../../test/fixtures'
import { installEventSource, mount, stubApi } from '../../test/harness'
import { visibleWords } from '../../test/visibleWords'
import '../setup'
import './backupsCard'
import './daemonCard'
import './serverCard'
import './setupCard'

/** Content inside a painted string: sizes and backup ids (dates are numeric). */
const CONTENT = [/\d[\d.,]* (B|KB|MB|GB)\b/g, /\d{8}-\d{6}/g]
const chrome = (root: Element, allowed: string[] = []): string[] =>
  visibleWords(root, allowed).filter((w) => /[A-Za-z]{2,}/.test(CONTENT.reduce((s, re) => s.replace(re, ''), w)))

beforeEach(installEventSource)

describe('textgate guard: system', () => {
  it('server, setup, daemon and backup cards paint no words, stale and unreachable included', async () => {
    stubApi({
      'GET /api/server': { stale: true, started_at: '2026-10-10T10:00:00Z', version: '9.9.9' },
      'GET /api/setup': { configured: false, has_api_key: false, steam_id: null },
      'GET /api/daemon': { state: 'unreachable', started_at: null, pid: null, journal_tail: [], restart_available_at: null },
      'GET /api/backups': [{ id: '20261010-100000', created_at: '2026-10-10T10:00:00Z', reason: 'nightly', size_bytes: 2048 }],
      'GET /api/commands': [makeSpec('reset')],
      'GET /api/jobs': [],
    })
    const el = mount('<server-card></server-card><setup-card></setup-card><daemon-card></daemon-card><backups-card></backups-card>')
    await screen.findByText('20261010-100000')
    await screen.findByText('Daemon unreachable')
    await screen.findByText('Stale')
    // The recovery command is content kuhy runs.
    expect(chrome(el, ['systemctl status steam-backlog-enforcer'])).toEqual([])
  })

  it('the restore dialog paints no words', async () => {
    stubApi({
      'GET /api/backups': [{ id: '20261010-100000', created_at: '2026-10-10T10:00:00Z', reason: 'before reset', size_bytes: 2048 }],
      'GET /api/commands': [makeSpec('reset')],
      'GET /api/jobs': [],
    })
    const el = mount('<backups-card></backups-card>')
    await userEvent.click(await screen.findByRole('button', { name: 'Restore…' }))
    const dialog = await screen.findByRole('dialog')
    // The phrase is the friction text kuhy types (settled decision 2).
    expect(chrome(el, ['restore backup 20261010-100000'])).toEqual([])
    expect(dialog).toBeInTheDocument()
  })

  it('the setup form paints no words, invalid values included', async () => {
    stubApi({ 'GET /api/setup': { configured: false, has_api_key: false, steam_id: null } })
    const el = mount('<setup-form></setup-form>')
    await screen.findByText('Not configured yet')
    await userEvent.type(screen.getByLabelText('Steam Web API key'), 'nothex')
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    await waitFor(() => {
      expect(screen.getByLabelText('Steam Web API key')).toHaveAttribute('aria-invalid', 'true')
    })
    expect(chrome(el)).toEqual([])
  })
})
