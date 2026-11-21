import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('Shell layout credit component', () => {
  it('contains kuhy-credit with placement="below" after health-badges', () => {
    const shellPath = resolve(import.meta.dirname, 'Shell.astro')
    const content = readFileSync(shellPath, 'utf-8')

    const healthBadgesIdx = content.indexOf('<health-badges></health-badges>')
    const creditIdx = content.indexOf('<kuhy-credit placement="below"></kuhy-credit>')

    expect(healthBadgesIdx).toBeGreaterThan(-1)
    expect(creditIdx).toBeGreaterThan(-1)
    expect(creditIdx).toBeGreaterThan(healthBadgesIdx)
  })

  it('registers kuhy-credit custom element', async () => {
    await import('@kuhyx/kuhy-credit')
    const el = customElements.get('kuhy-credit')
    expect(el).toBeDefined()
  })
})
