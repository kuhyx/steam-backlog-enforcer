// Pass-2 icon wiring for the health badges and the stale banner: subject and
// state are separate ids, the user's words show right of them, the spoken
// text (pill text, aria-label) stays.

import { describe, expect, it, vi } from 'vitest'
import { button } from '../test/events'
import { mount, stubApi } from '../test/harness'
import { useIcons } from '../test/iconLedger'
import { painted } from '../test/painted'
import { visibleWords } from '../test/visibleWords'
import './health'

const server = (over = {}) => ({ stale: false, started_at: '2026-10-10T10:00:00Z', version: '1.2.3', ...over })
const daemon = (state: string) => ({ state, started_at: null, pid: null, journal_tail: [], restart_available_at: null })

describe('health badges by id', () => {
  it('draws the subject and the state with their words and glyphs', async () => {
    useIcons({
      'server.heading': { word: 'web' },
      'health.ok': { word: 'fine', glyph: '🟢' },
      'daemon.heading': { word: 'guard' },
      'health.warn': { word: 'shaky' },
    })
    stubApi({ 'GET /api/server': server(), 'GET /api/daemon': daemon('restarting') })
    const el = mount('<health-badges></health-badges>')
    await vi.waitFor(() => { expect(el.querySelector('[data-state="Daemon restarting"]')).not.toBeNull() })
    const pills = [...el.querySelectorAll<HTMLElement>('.pill')]
    expect(painted(pills[0])).toBe('🌐Web🟢Fine')
    expect(painted(pills[1])).toBe('🛡️Guard⚠️Shaky')
    expect(pills[0]?.querySelector('.sr-only')?.textContent).toContain('Server ok')
    expect(pills[1]).toHaveAttribute('data-state', 'Daemon restarting')
    expect(visibleWords(el)).toEqual([])
  })

  it('keeps the plain glyphs without words, the unknown state as the ellipsis', () => {
    stubApi({ 'GET /api/server': () => new Promise(() => undefined), 'GET /api/daemon': () => new Promise(() => undefined) })
    const el = mount('<health-badges></health-badges>')
    expect(painted(el.querySelector('[data-state="Daemon …"]'))).toBe('🛡️…')
  })
})

describe('stale banner by id', () => {
  it('draws the stale mark and the restart icon from the ledger', async () => {
    useIcons({ 'health.stale': { word: 'old' }, 'server.restart': { word: 'reload', glyph: '♻️' } })
    stubApi({ 'GET /api/server': server({ stale: true }) })
    const el = mount('<stale-banner></stale-banner>')
    await vi.waitFor(() => { expect(el).toHaveTextContent('The web server is running stale code.') })
    const banner = el.firstElementChild
    expect(banner?.querySelector('.glyph [data-icon="health.stale"]')?.textContent).toBe('⚠️🌐')
    expect(banner?.querySelector('.glyph .icon-word')?.textContent).toBe('Old')
    expect(button(el, 'Restart server').textContent).toBe('♻️Reload')
  })
})
