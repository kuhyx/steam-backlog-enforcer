import { describe, expect, it, vi } from 'vitest'
import { must } from '../test/events'
import { bodiesOf } from '../test/harness'
import { C, D, N, at, count, field, input, press, q, start, url } from '../test/pickerHelpers'

describe('<icon-words-picker>: keys and saves', () => {
  it('starts at the first unanswered icon with its glyph, context, description and progress', async () => {
    start()
    await at(3)
    expect(q('.picker-id')).toHaveTextContent(C.id)
    expect(q('.picker-big')).toHaveTextContent(C.glyph)
    expect(q('.picker-context').textContent).toContain(C.glyph)
    expect(q('.picker-desc')).toHaveTextContent(C.desc)
    expect(q('[role=progressbar]')).toHaveAttribute('aria-valuenow', String(Math.round((2 / N) * 100)))
    const words = [...document.querySelectorAll('[data-word-slot]')].map((b) => b.textContent)
    expect(words).toEqual(C.words.map((w, i) => `${String(i + 1)}${w}`))
  })

  it('1/2/3 save a suggestion and advance', async () => {
    const { mock } = start()
    await at(3)
    press('2')
    await at(4)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ word: C.words[1] }])
    expect(q('[role=progressbar]')).toHaveAttribute('aria-valuenow', String(Math.round((3 / N) * 100)))
  })

  it('O focuses the own-word field; Enter saves a multi-word entry and advances', async () => {
    const { mock } = start()
    await at(3)
    expect(press('o')).toBe(false)
    expect(document.activeElement).toBe(field())
    field().value = '  My   OWN words '
    press('s', {}, field())
    must(field().form).requestSubmit()
    await at(4)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ word: 'My OWN words' }])
  })

  it('S skips (word null) and advances', async () => {
    const { mock } = start()
    await at(3)
    press('S')
    await at(4)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ word: null }])
  })

  it('7/8/9 swap the glyph and stay; 6 keeps the default', async () => {
    const { mock } = start()
    await at(3)
    press('8')
    await vi.waitFor(() => { expect(q('.picker-big')).toHaveTextContent(C.alts[1] ?? '') })
    expect(count()).toBe(`3 / ${N}`)
    expect(q('[data-glyph-slot="1"]')).toHaveAttribute('aria-pressed', 'true')
    press('6')
    await vi.waitFor(() => { expect(q('.picker-big')).toHaveTextContent(C.glyph) })
    expect(bodiesOf(mock, url(C.id))).toEqual([{ glyph: C.alts[1] }, { glyph: null }])
    expect(q('[data-glyph-slot="default"]')).toHaveAttribute('aria-pressed', 'true')
  })

  it('ignores keys while typing and keys with modifiers (Alt+digit is the nav)', async () => {
    const { mock } = start()
    await at(3)
    press('1', { altKey: true })
    press('2', { ctrlKey: true })
    press('3', { metaKey: true })
    press('s', {}, field())
    await Promise.resolve()
    expect(bodiesOf(mock, url(C.id))).toEqual([])
    expect(count()).toBe(`3 / ${N}`)
  })

  it('3, 9, upper-case O and the keep-default button reach their slots', async () => {
    const { mock } = start()
    await at(3)
    press('9')
    await vi.waitFor(() => { expect(q('.picker-big')).toHaveTextContent(C.alts[2] ?? '') })
    q('[data-glyph-slot="default"]').click()
    await vi.waitFor(() => { expect(q('.picker-big')).toHaveTextContent(C.glyph) })
    press('O')
    expect(document.activeElement).toBe(field())
    field().blur()
    press('3')
    await at(4)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ glyph: C.alts[2] }, { glyph: null }, { word: C.words[2] }])
  })

  it('ignores unknown keys, keys before the ledger loads and keys under an open dialog', async () => {
    const { mock } = start()
    press('1')
    await at(3)
    press('x')
    document.body.append(Object.assign(document.createElement('dialog'), { open: true }))
    press('S')
    await Promise.resolve()
    expect(bodiesOf(mock, url(C.id))).toEqual([])
    expect(count()).toBe(`3 / ${N}`)
  })

  it('keys still work while the show-words checkbox has focus; Esc leaves the field', async () => {
    const { mock } = start()
    await at(3)
    const box = input('input[name=show-words]')
    box.focus()
    press('S', {}, box)
    await at(4)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ word: null }])
    press('o')
    expect(document.activeElement).toBe(field())
    press('Escape', {}, field())
    expect(document.activeElement).not.toBe(field())
  })

  it('clicks work like keys', async () => {
    const { mock } = start()
    await at(3)
    q('[data-glyph-slot="0"]').click()
    await vi.waitFor(() => { expect(q('.picker-big')).toHaveTextContent(C.alts[0] ?? '') })
    q('[data-word-slot="0"]').click()
    await at(4)
    q('[data-skip]').click()
    await at(5)
    q('[data-go="-1"]').click()
    await at(4)
    q('[data-go="1"]').click()
    await at(5)
    expect(bodiesOf(mock, url(C.id))).toEqual([{ glyph: C.alts[0] }, { word: C.words[0] }])
    expect(bodiesOf(mock, url(D.id))).toEqual([{ word: null }])
  })
})
