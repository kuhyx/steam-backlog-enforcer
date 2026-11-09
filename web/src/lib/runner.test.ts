import { describe, expect, it, vi } from 'vitest'
import { jobHref, pageHref, runner } from './runner'

describe('runner bus', () => {
  it('delivers a run request with and without a preset', () => {
    const fn = vi.fn()
    const off = runner.onRun(fn)
    runner.run('scan')
    runner.run('pick-manual', { app_id: 5 })
    expect(fn).toHaveBeenNthCalledWith(1, { name: 'scan' })
    expect(fn).toHaveBeenNthCalledWith(2, { name: 'pick-manual', preset: { app_id: 5 } })
    off()
    runner.run('scan')
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('delivers palette requests until unsubscribed', () => {
    const fn = vi.fn()
    const off = runner.onPalette(fn)
    runner.openPalette()
    expect(fn).toHaveBeenCalledTimes(1)
    off()
    runner.openPalette()
    expect(fn).toHaveBeenCalledTimes(1)
  })
})

describe('hrefs', () => {
  it('gives every section a trailing slash', () => {
    expect(pageHref('/')).toBe('/')
    expect(pageHref('/library')).toBe('/library/')
    expect(pageHref('/library/')).toBe('/library/')
  })

  it('encodes the job id', () => {
    expect(jobHref('a b&c')).toBe('/jobs/?id=a%20b%26c')
  })
})
