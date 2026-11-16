// The system page paints every icon through the registry: the user's word
// shows right of the icon, a chosen alternative glyph replaces the default,
// and the spoken names stay as they were.

import { screen, waitFor } from '@testing-library/dom'
import { beforeEach, describe, expect, it } from 'vitest'
import type { DaemonStatus } from '../../api/contract'
import { makeSpec } from '../../test/fixtures'
import { installEventSource, mount, stubApi } from '../../test/harness'
import { useIcons } from '../../test/iconLedger'
import './backupsCard'
import './daemonCard'
import './serverCard'
import './setupCard'

const daemon = (over: Partial<DaemonStatus> = {}): DaemonStatus => ({
  state: 'running',
  started_at: '2026-10-10T10:00:00Z',
  pid: 4242,
  journal_tail: [],
  restart_available_at: null,
  ...over,
})
const words = (root: Element) => [...root.querySelectorAll('.icon-word')].map((w) => w.textContent)
const marks = (root: Element) => [...root.querySelectorAll('[data-icon]')].map((m) => m.textContent)

beforeEach(installEventSource)

describe('system page icons', () => {
  it('daemon card: state, pid and restart icons carry words and glyphs, names spoken', async () => {
    useIcons({ 'daemon.running': { word: 'alive', glyph: '💚' }, 'daemon.pid': { word: 'process' }, 'daemon.restart': { word: 'restart' } })
    stubApi({ 'GET /api/daemon': daemon() })
    const el = mount('<daemon-card></daemon-card>')
    await screen.findByText('4242')
    expect(words(el)).toEqual(expect.arrayContaining(['Alive', 'Process', 'Restart']))
    expect(marks(el)).toContain('💚')
    expect(screen.getByText('PID')).toHaveClass('sr-only')
    expect(screen.getByRole('button', { name: /Restart daemon/ })).toBeInTheDocument()
  })

  it('daemon card: the rate-limit countdown keeps the busy icon and its word', async () => {
    useIcons({ 'state.wait': { word: 'busy' } })
    const later = new Date(Date.now() + 90_000).toISOString()
    stubApi({ 'GET /api/daemon': daemon({ restart_available_at: later }) })
    const el = mount('<daemon-card></daemon-card>')
    await waitFor(() => {
      expect(words(el)).toEqual(['Busy'])
    })
    expect(screen.getByLabelText(/Restart available in/)).toBeInTheDocument()
  })

  it('server card: version, code state and restart carry the chosen icons', async () => {
    useIcons({ 'server.version': { word: 'build' }, 'state.yes': { word: 'fresh' }, 'server.restart': { glyph: '🚀' } })
    stubApi({ 'GET /api/server': { stale: false, started_at: '2026-10-10T10:00:00Z', version: '9.9.9' } })
    const el = mount('<server-card></server-card>')
    await screen.findByText('9.9.9')
    expect(words(el)).toEqual(['Build', 'Fresh'])
    expect(screen.getByRole('button', { name: 'Restart server' }).querySelector('[data-icon]')?.textContent).toBe('🚀')
    expect(screen.getByText('current')).toHaveClass('sr-only')
  })

  it('backups card: reason, restore and cancel icons go through the registry', async () => {
    useIcons({ 'backup.reason.reset': { word: 'wipe' }, 'backup.restore': { glyph: '⏪' }, 'action.cancel': { word: 'cancel' } })
    stubApi({
      'GET /api/backups': [{ id: '20261010-100000', created_at: '2026-10-10T10:00:00Z', reason: 'before reset', size_bytes: 2048 }],
      'GET /api/commands': [makeSpec('reset')],
      'GET /api/jobs': [],
    })
    const el = mount('<backups-card></backups-card>')
    await screen.findByText('20261010-100000')
    expect(words(el)).toEqual(['Wipe'])
    expect(screen.getByRole('button', { name: 'Restore…' }).querySelector('[data-icon]')?.textContent).toBe('⏪')
  })

  it('setup card: key, stored and edit icons carry the words, sentences stay spoken', async () => {
    useIcons({ 'setup.api-key': { word: 'key' }, 'setup.key-stored': { word: 'safe' },'syssetup.edit': { glyph: '📝' } })
    stubApi({ 'GET /api/setup': { configured: true, has_api_key: true, steam_id: '7656119800000000' } })
    const el = mount('<setup-card></setup-card>')
    await screen.findByText('Stored (never shown)')
    expect(words(el)).toEqual(['Key', 'Safe'])
    expect(screen.getByRole('link', { name: 'Open setup' }).querySelector('[data-icon]')?.textContent).toBe('📝')
  })
})
