import { describe, expect, it, vi } from 'vitest'
import { must } from '../test/events'
import { apiError, bodiesOf, stubApi } from '../test/harness'
import { A, B, C, N, at, count, field, input, press, q, start, url } from '../test/pickerHelpers'
import { wordsHidden } from './ledger'
import { ICONS } from './registry'

describe('<icon-words-picker>: moving, summary, errors', () => {
  it('←/→ move; a revisit shows the saved choice', async () => {
    start({ [A.id]: { word: A.words[2] ?? '', glyph: null }, [B.id]: { word: 'Mine all mine' }, [C.id]: { word: null } })
    await at(4)
    press('ArrowLeft')
    await at(3)
    expect(q('[data-skip]')).toHaveAttribute('aria-pressed', 'true')
    press('ArrowLeft')
    await at(2)
    expect(field().value).toBe('Mine all mine')
    press('ArrowLeft')
    await at(1)
    expect(q('[data-word-slot="2"]')).toHaveAttribute('aria-pressed', 'true')
    expect(field().value).toBe('')
    press('ArrowLeft')
    await at(1)
    press('ArrowRight')
    await at(2)
  })

  it('a failed glyph save keeps the field empty and reports the error', async () => {
    start()
    await at(3)
    stubApi({ [url(C.id)]: apiError(500, 'op_failed', 'disk full') })
    press('7')
    await vi.waitFor(() => { expect(q('.picker-status .notice-danger')).toHaveTextContent('disk full') })
    expect(field().value).toBe('')
    expect(field()).toHaveAttribute('aria-invalid', 'false')
  })

  it('refuses a bad own word before sending and flags the field', async () => {
    const { mock } = start()
    await at(3)
    field().value = 'x'.repeat(41)
    must(field().form).requestSubmit()
    expect(field()).toHaveAttribute('aria-invalid', 'true')
    expect(bodiesOf(mock, url(C.id))).toEqual([])
  })

  it('shows a server refusal and stays on the icon', async () => {
    start()
    await at(3)
    stubApi({ 'GET /api/icon-words': { version: 1, icons: {} }, [url(C.id)]: apiError(400, 'invalid_params', 'no') })
    field().value = 'fine'
    must(field().form).requestSubmit()
    await vi.waitFor(() => { expect(field()).toHaveAttribute('aria-invalid', 'true') })
    expect(q('.picker-status .notice-danger')).toHaveTextContent('no')
    expect(count()).toBe(`3 / ${N}`)
  })

  it('ends on a summary that jumps back to the first unanswered icon', async () => {
    const all = Object.fromEntries(ICONS.slice(0, -1).map((e) => [e.id, { word: null }]))
    start(all)
    await at(N)
    press('s')
    await vi.waitFor(() => { expect(q('.picker-summary')).toHaveTextContent(`${String(N)} / ${String(N)}`) })
    expect(document.querySelector('[data-jump]')).toBeNull()
    for (const k of ['1', '7', '6', 's']) press(k)
    await Promise.resolve()
    expect(document.querySelector('.picker-count')).toBeNull()
    press('ArrowLeft')
    await at(N)
  })

  it('opens on the summary when every icon is answered', async () => {
    start(Object.fromEntries(ICONS.map((e) => [e.id, { word: 'x' }])))
    await vi.waitFor(() => { expect(q('.picker-summary')).toHaveTextContent(`${String(N)} / ${String(N)}`) })
    expect(q('[data-go="1"]')).toBeDisabled()
  })

  it('offers the jump when icons are left unanswered', async () => {
    start()
    await at(3)
    press('ArrowRight')
    for (let i = 4; i <= N; i++) {
      await at(i)
      press('ArrowRight')
    }
    await vi.waitFor(() => { expect(q('.picker-summary')).toHaveTextContent(`2 / ${String(N)}`) })
    q('[data-jump]').click()
    await at(3)
  })

  it('the show-words switch flips the one setting', async () => {
    start()
    await at(3)
    const box = () => input('input[name=show-words]')
    expect(box().checked).toBe(true)
    box().click()
    expect(wordsHidden()).toBe(true)
    expect(box().checked).toBe(false)
    box().click()
    expect(wordsHidden()).toBe(false)
  })

  it('shows the error when the ledger cannot be read', async () => {
    stubApi({ 'GET /api/icon-words': apiError(500, 'op_failed', 'kept aside as x.corrupt') })
    document.body.innerHTML = '<icon-words-picker></icon-words-picker>'
    await vi.waitFor(() => { expect(q('.picker-status .notice-danger')).toHaveTextContent('x.corrupt') })
    expect(document.querySelector('.picker-count')).toBeNull()
  })
})
