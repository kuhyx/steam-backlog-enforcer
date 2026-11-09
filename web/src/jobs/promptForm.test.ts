import { afterEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import type { PickMode } from '../library/pick'
import { button, must, setValue, submit } from '../test/events'
import { makeLibGame } from '../test/fixtures'
import { apiError, bodiesOf, flush, stubApi } from '../test/harness'
import { hub, type PromptEvent } from './hub'
import { promptForm } from './promptForm'

// The real <game-browser> belongs to library/; the prompt only needs a `pick` slot.
class StubBrowser extends HTMLElement {
  pick: PickMode | null = null
}
if (!customElements.get('game-browser')) customElements.define('game-browser', StubBrowser)

const ANSWER = 'POST /api/jobs/j/answer'
const prompt = (over: Partial<PromptEvent> = {}): PromptEvent => ({
  seq: 1, ts: 't', type: 'prompt', prompt_id: 'q1', kind: 'text', message: 'Which one?', ...over,
})
function show(over: Partial<PromptEvent> = {}) {
  const form = promptForm('j', prompt(over))
  document.body.append(form)
  return form
}
const inputs = (form: HTMLElement) => [...form.querySelectorAll('input')]
const answerBodies = (mock: ReturnType<typeof stubApi>) => bodiesOf(mock, ANSWER)

afterEach(vi.restoreAllMocks)

describe('choice prompt', () => {
  const options = [
    { value: 'a', label: 'Alpha', detail: 'the first' },
    { value: 'b', label: 'Beta' },
  ]

  it('is a radio group, first option focusable first, nothing preselected', () => {
    const form = show({ kind: 'choice', options })
    const radios = inputs(form)
    expect(radios).toHaveLength(2)
    expect(radios[0]).toHaveAttribute('autofocus')
    expect(radios[1]).not.toHaveAttribute('autofocus')
    expect(form).toHaveTextContent('the first')
    expect(form.querySelectorAll('.choice-detail')).toHaveLength(1)
    expect(button(form, 'Answer')).toBeDisabled()
    expect(form).toHaveAttribute('aria-label', 'Job question')
  })

  it('sends the chosen value and hides the prompt', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const answered = vi.spyOn(hub, 'answered')
    const form = show({ kind: 'choice', options })
    inputs(form)[1]?.click()
    expect(form.querySelector('[data-value=b]')).toHaveClass('selected')
    expect(form.querySelector('[data-value=a]')).not.toHaveClass('selected')
    button(form, 'Answer').click()
    await vi.waitFor(() => { expect(answered).toHaveBeenCalledWith('j', 'q1') })
    expect(answerBodies(mock)).toEqual([{ prompt_id: 'q1', value: 'b' }])
  })

  it('honours a default and tolerates missing options', () => {
    const form = show({ kind: 'choice', default: 'a' })
    expect(button(form, 'Answer')).toBeEnabled()
    expect(inputs(form)).toHaveLength(0)
  })

  it('preselects the default option', () => {
    const form = show({ kind: 'choice', options, default: 'b' })
    expect(inputs(form)[1]?.checked).toBe(true)
    expect(form.querySelector('[data-value=b]')).toHaveClass('selected')
  })

  it('ignores Enter until something is chosen', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    submit(show({ kind: 'choice', options }))
    await flush()
    expect(answerBodies(mock)).toEqual([])
  })
})

describe('text prompt', () => {
  it('submits on Enter, even empty, starting from the default', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const form = show({ default: 'x' })
    const input = inputs(form)[0]
    expect(input).toHaveAttribute('autofocus')
    expect(input).toHaveAttribute('aria-label', 'Which one?')
    expect(input).toHaveValue('x')
    setValue(input, 'xy')
    submit(input)
    await vi.waitFor(() => { expect(answerBodies(mock)).toEqual([{ prompt_id: 'q1', value: 'xy' }]) })
  })

  it('sends an empty answer', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    submit(show())
    await vi.waitFor(() => { expect(answerBodies(mock)).toEqual([{ prompt_id: 'q1', value: '' }]) })
  })
})

describe('confirm prompt', () => {
  it('answers yes or no, yes focused by default', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const form = show({ kind: 'confirm' })
    expect(button(form, 'Yes')).toHaveAttribute('autofocus')
    expect(button(form, 'No')).not.toHaveAttribute('autofocus')
    button(form, 'Yes').click()
    await vi.waitFor(() => { expect(button(form, 'No')).toBeEnabled() })
    button(form, 'No').click()
    await vi.waitFor(() => { expect(answerBodies(mock)).toHaveLength(2) })
    expect(answerBodies(mock).map((b) => (b as { value: string }).value)).toEqual(['yes', 'no'])
  })

  it('focuses No when that is the default', () => {
    const form = show({ kind: 'confirm', default: 'no' })
    expect(button(form, 'No')).toHaveAttribute('autofocus')
    expect(button(form, 'Yes')).not.toHaveAttribute('autofocus')
  })

  it('disables both buttons while sending', async () => {
    let release: () => void = () => undefined
    stubApi({ [ANSWER]: () => new Promise<void>((r) => { release = r }) })
    const form = show({ kind: 'confirm' })
    button(form, 'Yes').click()
    await flush()
    expect(button(form, 'Yes')).toBeDisabled()
    expect(button(form, 'No')).toBeDisabled()
    release()
    await vi.waitFor(() => { expect(button(form, 'Yes')).toBeEnabled() })
  })
})

describe('phrase prompt', () => {
  it('stays disabled until the phrase is typed exactly', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const form = show({ kind: 'phrase', phrase: 'do it' })
    const answer = button(form, 'Answer')
    const input = inputs(form)[0]
    expect(input).toHaveAttribute('autofocus')
    setValue(input, 'do i')
    expect(answer).toBeDisabled()
    setValue(input, 'do it')
    expect(answer).toBeEnabled()
    answer.click()
    submit(answer)
    await vi.waitFor(() => { expect(answerBodies(mock)).toContainEqual({ prompt_id: 'q1', value: 'do it' }) })
  })

  it('starts from the default, and copes with a prompt that lost its phrase', () => {
    expect(button(show({ kind: 'phrase', phrase: 'do it', default: 'do it' }), 'Answer')).toBeEnabled()
    expect(button(show({ kind: 'phrase' }), 'Answer')).toBeEnabled()
  })
})

describe('answering', () => {
  it('shows the server error when the answer is refused', async () => {
    stubApi({ [ANSWER]: apiError(404, 'not_found', 'job is gone') })
    const form = show()
    button(form, 'Answer').click()
    await vi.waitFor(() => { expect(form).toHaveTextContent('job is gone') })
  })

  it('shows Sending… on the answer button', async () => {
    stubApi({ [ANSWER]: () => new Promise(() => undefined) })
    const form = show()
    button(form, 'Answer').click()
    await flush()
    expect(button(form, 'Sending…')).toBeDisabled()
  })
})

describe('game prompt', () => {
  const gprompt = (over: Partial<PromptEvent> = {}) => prompt({ prompt_id: 'g1', kind: 'game', message: 'Pick a game', app_ids: [1, 2], ...over })
  function showGame(over: Partial<PromptEvent> = {}) {
    const form = promptForm('j', gprompt(over))
    document.body.append(form)
    const browser = must(form.querySelector<StubBrowser>('game-browser'))
    return { form, browser, pick: () => must(browser.pick) }
  }

  it('embeds the browser in pick mode with only the offered ids', () => {
    const { form, pick } = showGame()
    expect(form).toHaveTextContent('2 games can be picked')
    expect(form).toHaveClass('prompt-game')
    expect(pick().appIds).toEqual(new Set([1, 2]))
    expect(pick().selected).toBeNull()
    expect(button(form, 'Select a game')).toBeDisabled()
  })

  it('selecting never submits; only the Pick button does', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const answered = vi.spyOn(hub, 'answered')
    q.library.set({ games: [makeLibGame({ app_id: 2, name: 'The Witcher 2' })] })
    const { form, pick } = showGame()
    pick().onSelect(2)
    expect(pick().selected).toBe(2)
    expect(answerBodies(mock)).toEqual([])
    button(form, 'Pick The Witcher 2').click()
    submit(form)
    await vi.waitFor(() => { expect(answered).toHaveBeenCalledWith('j', 'g1') })
    expect(answerBodies(mock)[0]).toEqual({ prompt_id: 'g1', value: '2' })
  })

  it('"Back to the list" answers an empty string', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const { form } = showGame()
    button(form, 'Back to the list').click()
    await vi.waitFor(() => { expect(answerBodies(mock)).toEqual([{ prompt_id: 'g1', value: '' }]) })
  })

  it('Enter does nothing without a selection, and submits one', async () => {
    const mock = stubApi({ [ANSWER]: undefined })
    const { form, pick } = showGame()
    submit(form)
    await flush()
    expect(answerBodies(mock)).toEqual([])
    pick().onSelect(1)
    submit(form)
    await vi.waitFor(() => { expect(answerBodies(mock)).toEqual([{ prompt_id: 'g1', value: '1' }]) })
  })

  it('names the game by id when it is not in the library', () => {
    q.library.set({ games: [] })
    const { form, pick } = showGame()
    pick().onSelect(1)
    expect(button(form, 'Pick 1')).toBeEnabled()
  })

  it('copes with a prompt that carries no app ids', () => {
    const { form, pick } = showGame({ app_ids: undefined })
    expect(form).toHaveTextContent('0 games can be picked')
    expect(pick().appIds.size).toBe(0)
  })

  it('shows Sending… meanwhile, then the error when the answer is refused', async () => {
    let fail = false
    let release: () => void = () => undefined
    stubApi({ [ANSWER]: () => (fail ? apiError(409, 'busy', 'job moved on') : new Promise<void>((r) => { release = r })) })
    const { form, pick } = showGame()
    pick().onSelect(1)
    button(form, 'Pick 1').click()
    await flush()
    expect(button(form, 'Sending…')).toBeDisabled()
    expect(button(form, 'Back to the list')).toBeDisabled()
    fail = true
    release()
    await flush()
    button(form, 'Back to the list').click()
    await vi.waitFor(() => { expect(form).toHaveTextContent('job moved on') })
  })
})
