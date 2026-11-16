import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { useIcons } from '../test/iconLedger'
import { glyph } from '../ui/build'
import { setWordsHidden } from './ledger'
import { decorateChrome, decorateIcons, iconFor, iconMark, iconWord } from './render'

// vitest runs from web/ (vitest.config.ts); jsdom loads no CSS, so read the rule.
const css = readFileSync(join(process.cwd(), 'src/styles/icons.css'), 'utf8')

describe('decorateChrome', () => {
  it('decorates the sidebar and top bar only', () => {
    useIcons({ 'nav.jobs': { word: 'jobs' }, 'palette.open': { word: 'find' } })
    document.body.innerHTML =
      '<aside class="sidebar"><a class="nav-link"><span data-icon="nav.jobs">⚙️</span></a></aside>' +
      '<header class="topbar"><button class="btn"><span data-icon="palette.open">🔍</span></button></header>' +
      '<main><span data-icon="nav.jobs">⚙️</span></main>'
    decorateChrome()
    expect([...document.querySelectorAll('.icon-word')].map((w) => w.textContent)).toEqual(['Jobs', 'Find'])
  })
})

describe('iconFor', () => {
  it('is the default glyph and no word without a ledger entry', () => {
    expect(iconFor('cmd.done')).toEqual({ id: 'cmd.done', glyph: '🏆', word: '', spoken: 'Done' })
  })

  it('draws the stored word in sentence case and swaps in the chosen glyph', () => {
    useIcons({ 'cmd.done': { word: 'got an HLTB win', glyph: '🎉' } })
    expect(iconFor('cmd.done')).toMatchObject({ glyph: '🎉', word: 'Got an HLTB win' })
  })

  it('has no word when skipped or hidden, but keeps the chosen glyph', () => {
    useIcons({ 'cmd.done': { word: null, glyph: '🏁' }, 'cmd.scan': { word: 'scan' } })
    expect(iconFor('cmd.done')).toMatchObject({ glyph: '🏁', word: '' })
    setWordsHidden(true)
    expect(iconFor('cmd.scan').word).toBe('')
  })

  it('ignores a stored glyph that is not one of the registered ones', () => {
    useIcons({ 'cmd.done': { glyph: '🍕' } })
    expect(iconFor('cmd.done').glyph).toBe('🏆')
  })
})

describe('glyph(id)', () => {
  it('paints the word to the right of the icon and keeps the spoken name', () => {
    useIcons({ 'nav.jobs': { word: 'my jobs' } })
    const el = glyph('nav.jobs')
    const [icon, word, spoken] = [...el.children]
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    expect(icon.textContent).toBe('⚙️')
    expect(word).toHaveClass('icon-word')
    expect(word).toHaveAttribute('aria-hidden', 'true')
    expect(word.textContent).toBe('My jobs')
    expect(spoken).toHaveClass('sr-only')
    expect(spoken.textContent).toBe('Jobs')
    expect(el).toHaveClass('glyph', 'has-word')
  })

  it('takes an explicit spoken name and class', () => {
    const el = glyph('cmd.scan', 'Run scan', 'job-cmd')
    expect(el.className).toBe('job-cmd')
    expect(el.querySelector('.sr-only')?.textContent).toBe('Run scan')
    expect(el.querySelector('.icon-word')).toBeNull()
  })

  it('still paints a raw glyph with the old signature', () => {
    const el = glyph('🧭', 'navigate')
    expect(el.querySelector('[aria-hidden]')?.textContent).toBe('🧭')
    expect(el.querySelector('.sr-only')?.textContent).toBe('navigate')
    expect(el.querySelector('.icon-word')).toBeNull()
  })
})

describe('icon pieces', () => {
  it('iconMark is the glyph alone, tagged with its id', () => {
    useIcons({ 'nav.store': { glyph: '🏪' } })
    const el = iconMark('nav.store', 'nav-icon')
    expect(el.className).toBe('nav-icon')
    expect(el).toHaveAttribute('data-icon', 'nav.store')
    expect(el).toHaveAttribute('aria-hidden', 'true')
    expect(el.textContent).toBe('🏪')
  })

  it('iconWord is null without a word, a tagged span with one', () => {
    expect(iconWord('nav.store')).toBeNull()
    useIcons({ 'nav.store': { word: 'shop' } })
    const w = iconWord('nav.store')
    expect(w).toHaveAttribute('data-icon-word', 'nav.store')
    expect(w?.textContent).toBe('Shop')
  })

  it('the CSS lays the word out on the right, vertically centred, never under', () => {
    const rule = /\.has-word\s*\{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(rule).toMatch(/display:\s*inline-flex/)
    expect(rule).toMatch(/align-items:\s*center/)
    expect(rule).not.toMatch(/column|wrap/)
  })
})

describe('decorateIcons (static Astro markup: sidebar, palette button)', () => {
  const markup = () => {
    document.body.innerHTML =
      '<a class="nav-link"><span class="nav-icon" aria-hidden="true" data-icon="nav.picks">🎯</span><kbd>3</kbd></a>' +
      '<span data-icon="no.such">❓</span>'
    return document.body
  }

  it('swaps the glyph and puts the word right after the icon, once', () => {
    useIcons({ 'nav.picks': { word: 'target', glyph: '🏹' } })
    const root = markup()
    decorateIcons(root)
    decorateIcons(root)
    const icon = root.querySelector('[data-icon="nav.picks"]')
    expect(icon?.textContent).toBe('🏹')
    expect(icon?.nextElementSibling).toHaveClass('icon-word')
    expect(icon?.nextElementSibling?.textContent).toBe('Target')
    expect(root.querySelectorAll('.icon-word')).toHaveLength(1)
    expect(icon?.parentElement).toHaveClass('has-word')
    expect(root.querySelector('[data-icon="no.such"]')?.textContent).toBe('❓')
  })

  it('removes the words again when they are hidden', () => {
    useIcons({ 'nav.picks': { word: 'target' } })
    const root = markup()
    decorateIcons(root)
    setWordsHidden(true)
    decorateIcons(root)
    expect(root.querySelector('.icon-word')).toBeNull()
    expect(root.querySelector('.nav-link')).not.toHaveClass('has-word')
    expect(root.querySelector('[data-icon="nav.picks"]')?.textContent).toBe('🎯')
  })
})
