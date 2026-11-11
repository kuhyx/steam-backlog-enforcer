import { describe, expect, it } from 'vitest'
import { since } from './dashboard'

describe('since', () => {
  it('paints a clock and the short span, speaking the full phrase', () => {
    const el = since(new Date(Date.now() - 5 * 60_000).toISOString())
    expect(el.querySelector('[aria-hidden="true"]')?.textContent).toBe('🕓 5 min')
    expect(el.querySelector('.sr-only')?.textContent).toBe('5 min ago')
  })

  it('paints "<1 min" while speaking "just now"', () => {
    const el = since(new Date().toISOString())
    expect(el.querySelector('[aria-hidden="true"]')?.textContent).toBe('🕓 <1 min')
    expect(el.querySelector('.sr-only')?.textContent).toBe('just now')
  })
})
