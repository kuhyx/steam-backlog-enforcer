// The install button's spoken label lives in the Astro pages, which vitest
// never renders: read their source. Install targets any game allowed today,
// not only the assigned one, so the label must not say "assigned".

import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const page = (file: string) => readFileSync(new URL(file, import.meta.url), 'utf8')

describe('install button label', () => {
  it.each(['../pages/index.astro', '../pages/library/index.astro'])('%s labels it "Install"', (file) => {
    const src = page(file)
    expect(src).toMatch(/name="install" label="Install"/)
    expect(src).not.toMatch(/Install assigned/)
  })
})
