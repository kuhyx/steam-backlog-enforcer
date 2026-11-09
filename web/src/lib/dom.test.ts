import { describe, expect, it, vi } from 'vitest'
import { append, define, h, hx, jsonAttr } from './dom'

describe('h', () => {
  it('sets string and number attributes, and bare booleans', () => {
    const el = h('input', { id: 'a', tabindex: 3, disabled: true })
    expect(el.id).toBe('a')
    expect(el.getAttribute('tabindex')).toBe('3')
    expect(el.getAttribute('disabled')).toBe('')
  })

  it('skips false, null and undefined attributes', () => {
    const el = h('div', { a: false, b: null, c: undefined })
    expect(el.attributes).toHaveLength(0)
  })

  it('turns on* attributes into listeners', () => {
    const onclick = vi.fn()
    const el = h('button', { onclick })
    el.click()
    expect(onclick).toHaveBeenCalledTimes(1)
  })

  it('flattens child arrays and skips empty children', () => {
    const el = h('p', {}, 'a', ['b', ['c', 4]], null, undefined, false, h('i'))
    expect(el.textContent).toBe('abc4')
    expect(el.querySelector('i')).not.toBeNull()
  })
})

describe('append', () => {
  it('ignores empties and appends text and nodes', () => {
    const el = document.createElement('div')
    append(el, null)
    append(el, undefined)
    append(el, false)
    append(el, 7)
    append(el, document.createElement('b'))
    expect(el.innerHTML).toBe('7<b></b>')
  })
})

describe('hx', () => {
  it('builds a custom-tag element', () => {
    const el = hx('x-thing', { a: '1' }, 'hi')
    expect(el.tagName).toBe('X-THING')
    expect(el.getAttribute('a')).toBe('1')
    expect(el.textContent).toBe('hi')
  })
})

describe('define', () => {
  it('registers once and ignores a second definition', () => {
    class A extends HTMLElement {}
    class B extends HTMLElement {}
    define('x-dom-define', A)
    define('x-dom-define', B)
    expect(customElements.get('x-dom-define')).toBe(A)
  })
})

describe('jsonAttr', () => {
  const el = h('div', { ok: '{"a":1}', bad: '{nope' })
  it('parses valid JSON', () => {
    expect(jsonAttr(el, 'ok', null)).toEqual({ a: 1 })
  })
  it('falls back when absent or invalid', () => {
    expect(jsonAttr(el, 'missing', 'fb')).toBe('fb')
    expect(jsonAttr(el, 'bad', 'fb')).toBe('fb')
  })
})
