// Static Astro markup outside the sidebar and top bar (the 404 home link) opts
// in with `data-static-icons`; the boot decoration then paints the user's
// word and glyph there too.

import { describe, expect, it } from 'vitest'
import { useIcons } from '../test/iconLedger'
import { decorateChrome } from './render'

const markup = (attr: string) => `
  <div class="actions" ${attr}>
    <a href="/" aria-label="Back to the dashboard"><span aria-hidden="true" data-icon="nav.dashboard">🏠</span></a>
  </div>`

describe('decorateChrome and data-static-icons', () => {
  it('decorates a tagged container with the word and the alternative glyph', () => {
    useIcons({ 'nav.dashboard': { word: 'home', glyph: '🏡' } })
    document.body.innerHTML = markup('data-static-icons')
    decorateChrome()
    const icon = document.querySelector('[data-icon]')
    expect(icon?.textContent).toBe('🏡')
    expect(icon?.nextElementSibling).toHaveClass('icon-word')
    expect(icon?.nextElementSibling?.textContent).toBe('Home')
    expect(icon?.parentElement).toHaveClass('has-word')
    expect(document.querySelector('a')).toHaveAttribute('aria-label', 'Back to the dashboard')
  })

  it('leaves untagged containers alone', () => {
    useIcons({ 'nav.dashboard': { word: 'home', glyph: '🏡' } })
    document.body.innerHTML = markup('')
    decorateChrome()
    expect(document.querySelector('[data-icon]')?.textContent).toBe('🏠')
    expect(document.querySelector('.icon-word')).toBeNull()
  })
})
