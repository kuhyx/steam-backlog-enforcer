import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NAV } from '../shell/nav'
import { runner, type RunRequest } from '../lib/runner'
import { must, setValue } from '../test/events'
import { makeSpec } from '../test/fixtures'
import { apiError, stubApi } from '../test/harness'
import { CommandPaletteElement, go } from './palette'

const SPECS = [
  makeSpec('scan', { description: 'Scan achievements.' }),
  makeSpec('unblock', { description: 'Open the store.', friction: { phrase_template: 'x' } }),
  makeSpec('status', { kind: 'view', description: 'Show status.' }),
  makeSpec('pick', { description: 'Pick next.', locked_reason: 'Locked by a pick' }),
]
const TOTAL = SPECS.length + NAV.length

const assign = vi.fn()
const runs: RunRequest[] = []
let offRun = (): void => undefined

function open(specs = SPECS) {
  stubApi({ 'GET /api/commands': specs })
  const el = new CommandPaletteElement()
  document.body.append(el)
  el.open()
  return el
}
const box = () => must(document.querySelector<HTMLInputElement>('[role=combobox]'))
const options = () => [...document.querySelectorAll<HTMLElement>('[role=option]')]
const active = () => options().findIndex((o) => o.getAttribute('aria-selected') === 'true')
/** The option whose spoken title (the glyph's sr-only label) is `title`. */
const opt = (title: string) => must(options().find((o) => o.querySelector('.palette-title .glyph .sr-only')?.textContent === title))
const hint = (o: HTMLElement) => must(o.querySelector('.palette-hint'))
const key = (k: string) => box().dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
const loaded = () => vi.waitFor(() => {
  expect(options().length).toBeGreaterThan(0)
  expect(document.body).not.toHaveTextContent('Loading commands')
})

describe('CommandPaletteElement', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { assign })
    offRun = runner.onRun((r) => runs.push(r))
  })
  afterEach(() => {
    offRun()
    runs.length = 0
    assign.mockClear()
  })

  it('lists every command, then the sections, and focuses the box', async () => {
    const el = open()
    await loaded()
    expect(el.isOpen).toBe(true)
    expect(options()).toHaveLength(TOTAL)
    expect(hint(opt('Scan'))).toHaveTextContent('▶️run')
    expect(hint(opt('Unblock'))).toHaveTextContent('▶️⌨️run · confirm')
    expect(hint(opt('Status'))).toHaveTextContent('↗️open /')
    expect(opt('Pick').querySelector('.pill')).toHaveTextContent('🔒locked')
    expect(opt('Pick').querySelector('.palette-detail')).toHaveTextContent('Locked by a pick')
    expect(opt('Pick')).not.toHaveTextContent('Pick next.')
    expect(opt('Scan').querySelector('.palette-detail')).toHaveTextContent('Scan achievements.')
    expect(document.body).toHaveTextContent('Go to Dashboard')
    expect(document.activeElement).toBe(box())
  })

  it('opens from the runner bus, closes when a run starts, and cleans up on removal', () => {
    stubApi({ 'GET /api/commands': SPECS })
    const el = new CommandPaletteElement()
    document.body.append(el)
    runner.openPalette()
    expect(el.isOpen).toBe(true)
    runner.run('scan')
    expect(el.isOpen).toBe(false)
    runner.openPalette()
    el.remove()
    expect(el.isOpen).toBe(false)
    runner.openPalette()
    expect(el.isOpen).toBe(false)
  })

  it('toggles and ignores a second open', async () => {
    const el = open()
    await loaded()
    el.open()
    expect(options()).toHaveLength(TOTAL)
    el.toggle()
    expect(el.isOpen).toBe(false)
    el.toggle()
    expect(el.isOpen).toBe(true)
  })

  it('closes on Escape and on its close button', () => {
    const el = open()
    el.querySelector('dialog')?.dispatchEvent(new Event('cancel', { cancelable: true }))
    expect(el.isOpen).toBe(false)
    el.open()
    el.querySelector<HTMLButtonElement>('.dialog-close')?.click()
    expect(el.isOpen).toBe(false)
  })

  it('shows loading, then the load error', async () => {
    let fail: (r: unknown) => void = () => undefined
    stubApi({ 'GET /api/commands': () => new Promise((r) => { fail = r }) })
    const el = new CommandPaletteElement()
    document.body.append(el)
    el.open()
    expect(document.body).toHaveTextContent('Loading commands')
    fail(apiError(500, 'op_failed', 'catalog broken'))
    await vi.waitFor(() => {
      expect(document.body).toHaveTextContent('catalog broken')
    })
    expect(document.body).not.toHaveTextContent('Loading commands')
    expect(options()).toHaveLength(NAV.length)
  })

  it('filters by text and says when nothing matches', async () => {
    open()
    await loaded()
    setValue(box(), 'store')
    expect(options()).toHaveLength(2)
    setValue(box(), 'zzz')
    expect(document.body).toHaveTextContent('No command matches “zzz”.')
    expect(box()).not.toHaveAttribute('aria-activedescendant')
    expect(active()).toBe(-1)
  })

  it('reopens with an empty box and the first entry active', async () => {
    const el = open()
    await loaded()
    setValue(box(), 'store')
    el.close()
    el.open()
    expect(box()).toHaveValue('')
    expect(options()).toHaveLength(TOTAL)
    expect(active()).toBe(0)
  })

  it('moves with arrows and pages, clamped, and announces the active option', async () => {
    open()
    await loaded()
    expect(key('ArrowDown')).toBe(false)
    key('ArrowDown')
    expect(active()).toBe(2)
    expect(box().getAttribute('aria-activedescendant')).toBe(options()[2]?.id)
    key('ArrowUp')
    key('ArrowUp')
    key('ArrowUp')
    expect(active()).toBe(0)
    key('PageDown')
    expect(active()).toBe(8)
    key('PageDown')
    expect(active()).toBe(TOTAL - 1)
    key('ArrowDown')
    expect(active()).toBe(TOTAL - 1)
    key('PageUp')
    expect(active()).toBe(TOTAL - 9)
    key('PageUp')
    key('PageUp')
    expect(active()).toBe(0)
  })

  it('the pointer moves the highlight, and a typed edit resets it', async () => {
    open()
    await loaded()
    const second = options()[1]
    second.dispatchEvent(new MouseEvent('mousemove'))
    expect(active()).toBe(1)
    expect(second).toHaveClass('active')
    second.dispatchEvent(new MouseEvent('mousemove'))
    expect(active()).toBe(1)
    setValue(box(), 's')
    expect(active()).toBe(0)
  })

  it('Enter runs a job command', async () => {
    open()
    await loaded()
    expect(key('Enter')).toBe(false)
    expect(runs).toEqual([{ name: 'scan' }])
  })

  it('Enter on a view command navigates and closes', async () => {
    const el = open()
    await loaded()
    setValue(box(), 'show status')
    key('Enter')
    expect(runs).toEqual([])
    expect(assign).toHaveBeenCalledWith('/')
    expect(el.isOpen).toBe(false)
  })

  it('clicking a section navigates and closes', async () => {
    const el = open()
    await loaded()
    opt('Go to Jobs').click()
    expect(assign).toHaveBeenCalledWith('/jobs/')
    expect(el.isOpen).toBe(false)
  })

  it('Enter with nothing shown does nothing, and other keys are ignored', async () => {
    const el = open()
    await loaded()
    setValue(box(), 'zzz')
    expect(key('Enter')).toBe(true)
    expect(key('Tab')).toBe(true)
    expect(runs).toEqual([])
    expect(el.isOpen).toBe(true)
  })
})

describe('go', () => {
  it('loads the section as a static page', () => {
    vi.stubGlobal('location', { assign })
    go('/library')
    expect(assign).toHaveBeenCalledWith('/library/')
    assign.mockClear()
  })
})
