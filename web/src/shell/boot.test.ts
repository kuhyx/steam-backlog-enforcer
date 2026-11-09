import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { q, refreshAfterJob } from '../api/queries'
import { hub } from '../jobs/hub'
import { runner } from '../lib/runner'
import { must } from '../test/events'
import { Reply, stubApi } from '../test/harness'
import { BUILD_POLL_MS, boot, buildOf, checkBuild, onShellKey, watchSetup } from './boot'

const loc = { assign: vi.fn(), replace: vi.fn(), reload: vi.fn(), pathname: '/gaming/' }
const key = (init: KeyboardEventInit) => new KeyboardEvent('keydown', { cancelable: true, ...init })
const palette = () => ({ toggle: vi.fn() })

beforeEach(() => {
  vi.stubGlobal('location', loc)
})
afterEach(() => {
  for (const f of Object.values(loc)) if (typeof f === 'function') f.mockClear()
  hub.onTerminal = () => undefined
})

describe('onShellKey', () => {
  it.each([{ ctrlKey: true }, { metaKey: true }])('%j + K toggles the palette', (mod) => {
    const p = palette()
    const e = key({ key: 'K', ...mod })
    onShellKey(e, p)
    expect(p.toggle).toHaveBeenCalledTimes(1)
    expect(e.defaultPrevented).toBe(true)
  })

  it('leaves the palette shut while a wide dialog owns the screen, or when there is none', () => {
    document.body.innerHTML = '<dialog open class="dialog dialog-wide"></dialog>'
    const p = palette()
    const e = key({ key: 'k', ctrlKey: true })
    onShellKey(e, p)
    expect(p.toggle).not.toHaveBeenCalled()
    expect(e.defaultPrevented).toBe(true)
    document.body.replaceChildren()
    expect(() => {
      onShellKey(key({ key: 'k', ctrlKey: true }), null)
    }).not.toThrow()
  })

  it('Alt+digit jumps to the numbered section', () => {
    const e = key({ key: '3', altKey: true })
    onShellKey(e, null)
    expect(loc.assign).toHaveBeenCalledWith('/picks/')
    expect(e.defaultPrevented).toBe(true)
  })

  it('ignores a digit without Alt, with Ctrl or Meta, and unknown digits', () => {
    for (const init of [{ key: '3' }, { key: '9', altKey: true }, { key: '2', altKey: true, ctrlKey: true }, { key: '2', altKey: true, metaKey: true }]) {
      const e = key(init)
      onShellKey(e, null)
      expect(e.defaultPrevented).toBe(false)
    }
    expect(loc.assign).not.toHaveBeenCalled()
  })

  it('does nothing while a dialog is open', () => {
    document.body.innerHTML = '<dialog open></dialog>'
    onShellKey(key({ key: '2', altKey: true }), null)
    expect(loc.assign).not.toHaveBeenCalled()
  })
})

describe('watchSetup', () => {
  it('sends an unconfigured install to Setup', async () => {
    stubApi({ 'GET /api/setup': { configured: false, has_api_key: false, steam_id: null } })
    const off = watchSetup('/library/')
    await vi.waitFor(() => { expect(loc.replace).toHaveBeenCalledWith('/setup/') })
    off()
  })

  it('leaves a configured install, and an unanswered or failed check, alone', async () => {
    stubApi({ 'GET /api/setup': { configured: true, has_api_key: true, steam_id: '1' } })
    const off = watchSetup('/')
    await vi.waitFor(() => { expect(q.setup.state.loading).toBe(false) })
    off()
    q.setup.reset()
    stubApi({ 'GET /api/setup': new Reply(500, { error: 'op_failed', message: '' }) })
    const off2 = watchSetup('/')
    await vi.waitFor(() => { expect(q.setup.state.loading).toBe(false) })
    expect(loc.replace).not.toHaveBeenCalled()
    off2()
  })

  it.each(['/setup', '/setup/'])('does not watch on the Setup page itself (%s)', (path) => {
    const mock = stubApi({})
    const off = watchSetup(path)
    off()
    expect(mock).not.toHaveBeenCalled()
  })
})

describe('build stamp', () => {
  const page = (build: string) => `<html><head><meta name="sbe-build" content="${build}"></head></html>`

  it('reads the stamp from HTML, or null', () => {
    expect(buildOf(page('abc'))).toBe('abc')
    expect(buildOf('<html></html>')).toBeNull()
  })

  it('reloads when the served build differs', async () => {
    stubApi({ 'GET /gaming/': new Reply(200, undefined, page('new')) })
    await expect(checkBuild('old')).resolves.toBe(true)
    expect(loc.reload).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['the same build', new Reply(200, undefined, '<meta name="sbe-build" content="old">')],
    ['no stamp', new Reply(200, undefined, '<html></html>')],
    ['an error page', new Reply(500, undefined, page('new'))],
  ])('does not reload for %s', async (_name, reply) => {
    stubApi({ 'GET /gaming/': reply })
    await expect(checkBuild('old')).resolves.toBe(false)
    expect(loc.reload).not.toHaveBeenCalled()
  })

  it('tries again later when the server is down', async () => {
    stubApi({})
    await expect(checkBuild('old')).resolves.toBe(false)
    expect(loc.reload).not.toHaveBeenCalled()
  })
})

describe('boot', () => {
  const added: [string, EventListenerOrEventListenerObject][] = []
  beforeEach(() => {
    vi.useFakeTimers()
    const real = window.addEventListener.bind(window)
    vi.spyOn(window, 'addEventListener').mockImplementation((type: string, fn: EventListenerOrEventListenerObject, o?: boolean | AddEventListenerOptions) => {
      added.push([type, fn])
      real(type, fn, o)
    })
    stubApi({ 'GET /api/setup': { configured: true, has_api_key: true, steam_id: '1' }, 'GET /gaming/': new Reply(200, undefined, '<meta name="sbe-build" content="new">') })
  })
  afterEach(() => {
    for (const [t, f] of added.splice(0)) window.removeEventListener(t, f)
    vi.restoreAllMocks()
  })

  function page(extra = '') {
    document.head.innerHTML = extra
    document.body.innerHTML = '<command-palette></command-palette><button data-open-palette></button>'
    const el = must(document.querySelector<HTMLElement & { toggle: () => void }>('command-palette'))
    const toggle = vi.fn()
    el.toggle = toggle
    return toggle
  }

  it('wires refresh-on-job-end, shell keys and the palette button', () => {
    const toggle = page()
    const open = vi.fn()
    const off = runner.onPalette(open)
    boot()
    expect(hub.onTerminal).toBe(refreshAfterJob)
    window.dispatchEvent(key({ key: 'k', ctrlKey: true }))
    expect(toggle).toHaveBeenCalledTimes(1)
    document.querySelector<HTMLElement>('[data-open-palette]')?.click()
    expect(open).toHaveBeenCalledTimes(1)
    off()
  })

  it('tolerates a page without a palette or palette button', () => {
    document.body.replaceChildren()
    expect(() => {
      boot()
    }).not.toThrow()
    window.dispatchEvent(key({ key: 'k', ctrlKey: true }))
  })

  it('polls the build stamp only when the page has one', async () => {
    page('<meta name="sbe-build" content="old">')
    boot()
    await vi.advanceTimersByTimeAsync(BUILD_POLL_MS)
    expect(loc.reload).toHaveBeenCalledTimes(1)
  })

  it('does not poll for a build without a stamp', async () => {
    page()
    boot()
    await vi.advanceTimersByTimeAsync(BUILD_POLL_MS * 2)
    expect(loc.reload).not.toHaveBeenCalled()
  })
})
