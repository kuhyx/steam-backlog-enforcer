// Pass-2 icon wiring for the command UI: the user's word shows right of the
// icon, a chosen alternative glyph replaces the default, and the spoken
// names (aria-label, .sr-only) stay as they were.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeSpec, makePending } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import { useIcons } from '../test/iconLedger'
import { must } from '../test/events'
import { painted } from '../test/painted'
import { visibleWords } from '../test/visibleWords'
import { NAV } from '../shell/nav'
import './commandButton'
import { CommandPaletteElement } from './palette'
import { PendingCountdown } from './pendingCountdown'
import { commandFlags, fillHint, lockedNotice, terminalFallback } from './runnerParts'

describe('command button and card', () => {
  it('draws the lock badge with its word and glyph, aria unchanged', async () => {
    useIcons({ 'state.locked': { word: 'closed', glyph: '🔐' } })
    stubApi({ 'GET /api/commands': [makeSpec('scan', { locked_reason: 'A pick is active' })] })
    const el = mount('<command-button name="scan"></command-button>')
    await vi.waitFor(() => { expect(el.querySelector('.cmd-lock')).not.toBeNull() })
    const lock = must(el.querySelector('.cmd-lock'))
    expect(lock.textContent).toBe('🔐Closed')
    expect(lock.querySelector('.icon-word')).toHaveAttribute('data-icon-word', 'state.locked')
    expect(el.querySelector('button')).toHaveAttribute('aria-label', 'Run scan')
    expect(el.querySelector('button')).toHaveAttribute('aria-description', 'A pick is active')
    expect(visibleWords(el)).toEqual([])
  })

  it('draws the root and countdown flags of a card by id', async () => {
    useIcons({ 'cmdflag.root': { word: 'admin' }, 'cmdflag.countdown': { glyph: '⏲️' } })
    stubApi({ 'GET /api/commands': [makeSpec('gaming-reset', { privileged: true, friction: { phrase_template: 'x', countdown_seconds: 300 } })] })
    const el = mount('<command-card name="gaming-reset"></command-card>')
    await vi.waitFor(() => { expect(el.querySelector('.cmd-name .pill')).not.toBeNull() })
    const flags = [...el.querySelectorAll('.cmd-name .pill')]
    expect(flags.map((f) => f.getAttribute('aria-label'))).toEqual(['root', 'countdown'])
    expect(flags[0]?.textContent).toBe('🔑Admin')
    expect(flags[1]?.textContent).toBe('⏲️')
  })
})

describe('command palette', () => {
  it('shows the search icon and its word in the placeholder, hint icons by id', async () => {
    useIcons({ 'cmdpal.search': { word: 'find' }, 'cmdpal.open': { word: 'page', glyph: '🔗' }, 'cmdpal.go': { word: 'jump' } })
    stubApi({ 'GET /api/commands': [makeSpec('status', { kind: 'view', description: 'Show status.' })] })
    const el = new CommandPaletteElement()
    document.body.append(el)
    el.open()
    await vi.waitFor(() => { expect(document.querySelectorAll('[role=option]').length).toBeGreaterThan(NAV.length + 1) })
    expect(document.querySelector<HTMLInputElement>('[role=combobox]')).toHaveAttribute('placeholder', '🔍 Find')
    const hints = [...document.querySelectorAll('.palette-hint')]
    expect(hints[0]?.textContent).toContain('🔗Page')
    expect(hints[0]?.querySelector('.sr-only')?.textContent).toBe('open /')
    expect(hints.at(-1)?.textContent).toContain('🧭Jump')
  })
})

describe('run dialog parts', () => {
  it('draws the command flags by id', () => {
    useIcons({ 'cmdflag.readonly': { word: 'safe' }, 'cmdflag.cancellable': { glyph: '🛑' } })
    const flags = commandFlags(makeSpec('scan', { mutating: false, cancellable: true }))
    const [, readonly, cancellable] = flags
    expect(painted(readonly)).toBe('👁️Safe')
    expect(readonly?.querySelector('.sr-only')?.textContent).toBe('Read-only')
    expect(painted(cancellable)).toBe('🛑')
  })

  it('paints the lock mark in the warning notice and keeps the spoken reason', () => {
    useIcons({ 'state.locked': { word: 'sealed' } })
    const el = lockedNotice('Daemon is down')
    expect(el).toHaveAttribute('aria-label', 'Locked: Daemon is down')
    expect(el.textContent).toBe('🔒Sealed')
    expect(el.querySelector('.notice-icon')).toHaveAttribute('data-icon', 'state.locked')
  })

  it('draws the fill hint and the terminal fallback by id', () => {
    useIcons({ 'runner.fill': { word: 'above' }, 'runner.terminal': { glyph: '🐚' } })
    expect(fillHint(['app_id']).textContent).toContain('⬆️Above')
    const [line] = terminalFallback('sudo ./run.sh gaming-unblock')
    expect(line).toHaveAttribute('aria-label', 'Run it from a terminal instead:')
    expect(line.textContent).toBe('🐚')
  })
})

describe('pending countdown', () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: Date.parse('2026-10-10T10:00:00Z') })
  })
  const made: PendingCountdown[] = []
  afterEach(() => {
    for (const c of made.splice(0)) c.dispose()
  })

  it('draws the lock beside the clock and the heartbeat, words and glyphs from the ledger', () => {
    useIcons({ 'state.locked': { word: 'locked' }, 'pending.beat': { word: 'pulse', glyph: '💗' } })
    const cbs = { onCommitted: vi.fn(), onCancel: vi.fn(), onRearm: vi.fn() }
    const countdown = new PendingCountdown(makePending({ ready_at: '2026-10-10T10:00:30Z' }), cbs)
    made.push(countdown)
    document.body.append(countdown.el)
    const clock = must(countdown.el.querySelector('.countdown-clock'))
    expect(clock.textContent).toContain('🔒Locked')
    expect(clock.querySelector('.sr-only')?.textContent).toBe('until commit unlocks')
    expect(countdown.el.textContent).toContain('💗Pulse 0s')
    expect(countdown.el.querySelector('button')).toHaveAttribute('aria-label', 'Cancel countdown')
    expect(countdown.el.querySelector('button')?.textContent).toBe('✖️')
  })
})
