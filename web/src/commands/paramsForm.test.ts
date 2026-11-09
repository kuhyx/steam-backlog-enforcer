import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ParamSpec } from '../api/contract'
import type { ParamValues } from './params'
import { ParamsForm } from './paramsForm'
import { must } from '../test/events'

const SPECS: ParamSpec[] = [
  { name: 'app_id', label: 'Game', type: 'app_id', required: true },
  { name: 'days', label: 'Days', type: 'int', required: false, min: 1, max: 9, help: 'How long.' },
  { name: 'note', label: 'Note', type: 'string', required: false },
]
const GAMES = [{ app_id: 5, name: 'Five' }]

function make(over: { specs?: ParamSpec[]; values?: ParamValues; disabled?: boolean } = {}) {
  const onChange = vi.fn()
  const form = new ParamsForm({
    specs: over.specs ?? SPECS,
    values: over.values ?? { app_id: '', days: '', note: '' },
    disabled: over.disabled ?? false,
    onChange,
  })
  document.body.append(...form.nodes)
  const input = (label: RegExp | string) => must(document.querySelector<HTMLInputElement>(`#${labelFor(label)}`))
  return { form, onChange, input }
}

function labelFor(text: RegExp | string): string {
  const label = [...document.querySelectorAll('label')].find((l) => (typeof text === 'string' ? l.textContent === text : text.test(l.textContent)))
  return label?.getAttribute('for') ?? ''
}

describe('ParamsForm', () => {
  it('renders one labelled field per spec, marking the required ones', () => {
    const { input } = make()
    expect(input(/Game/)).toHaveAttribute('list')
    expect(input(/Game/)).toHaveAttribute('inputmode', 'numeric')
    expect(input(/Game/)).toHaveAttribute('autofocus')
    expect(input(/Game/)).toBeRequired()
    expect(document.body).toHaveTextContent('Game *')
    expect(input('Days')).toHaveAttribute('type', 'number')
    expect(input('Days')).toHaveAttribute('min', '1')
    expect(input('Days')).toHaveAttribute('max', '9')
    expect(input('Days')).not.toHaveAttribute('autofocus')
    expect(input('Note')).toHaveAttribute('type', 'text')
    expect(input('Note')).not.toHaveAttribute('inputmode')
    expect(input('Note')).not.toHaveAttribute('list')
    expect(document.body).toHaveTextContent('Type an app id or pick a game from the list.')
    expect(document.body).toHaveTextContent('How long.')
  })

  it('offers the known games in a datalist and names the chosen one', async () => {
    const { form, input } = make()
    form.refresh(GAMES)
    expect(document.querySelector('datalist option')).toHaveValue('5')
    expect(document.querySelector('datalist option')).toHaveTextContent('Five')
    await userEvent.type(input(/Game/), '5')
    expect(document.querySelector('.field-help')).toHaveTextContent('Five')
    form.refresh(GAMES)
    expect(document.querySelectorAll('datalist option')).toHaveLength(1)
  })

  it('shows errors only once asked to', () => {
    const { form, input } = make()
    expect(document.body).not.toHaveTextContent('Game is required.')
    form.refresh(GAMES, true)
    expect(document.body).toHaveTextContent('Game is required.')
    expect(input(/Game/)).toHaveClass('input-bad')
    expect(input(/Game/)).toHaveAttribute('aria-invalid', 'true')
    expect(document.querySelector('.field-help')).toHaveClass('text-danger')
    form.refresh(GAMES, false)
    expect(input(/Game/)).not.toHaveClass('input-bad')
    expect(input(/Game/)).toHaveAttribute('aria-invalid', 'false')
  })

  it('keeps the error setting across a games-only refresh', () => {
    const { form } = make()
    form.refresh(GAMES, true)
    form.refresh([{ app_id: 6, name: 'Six' }])
    expect(document.body).toHaveTextContent('Game is required.')
    form.refresh()
    expect(document.body).toHaveTextContent('Game is required.')
  })

  it('treats a value the form has not set yet as empty', () => {
    const { input, form } = make({ values: {} })
    expect(input('Note')).toHaveValue('')
    form.refresh([], true)
    expect(document.body).toHaveTextContent('Game is required.')
  })

  it('reports every edit with the full value set', async () => {
    const { input, onChange } = make()
    await userEvent.type(input('Note'), 'hi')
    expect(onChange).toHaveBeenLastCalledWith({ app_id: '', days: '', note: 'hi' })
    await userEvent.type(input('Days'), '3')
    expect(onChange).toHaveBeenLastCalledWith({ app_id: '', days: '3', note: 'hi' })
  })

  it('disables every field', () => {
    const { input } = make({ disabled: true })
    expect(input('Note')).toBeDisabled()
    expect(input(/Game/)).toBeDisabled()
  })

  it('renders a bool as a checkbox that toggles 0/1', async () => {
    const box: ParamSpec[] = [{ name: 'replace', label: 'Replace', type: 'bool', required: false, default: 0 }]
    const { input, onChange, form } = make({ specs: box, values: { replace: '0' } })
    form.refresh([], true)
    const check = input('Replace')
    expect(check).toHaveAttribute('type', 'checkbox')
    expect(check).not.toBeChecked()
    expect(check).not.toHaveAttribute('autofocus')
    await userEvent.click(check)
    expect(check).toBeChecked()
    expect(onChange).toHaveBeenLastCalledWith({ replace: '1' })
    await userEvent.click(check)
    expect(onChange).toHaveBeenLastCalledWith({ replace: '0' })
  })

  it('starts a bool checked from "1" and shows its help', () => {
    const box: ParamSpec[] = [{ name: 'on', label: 'On', type: 'bool', required: false, help: 'Be on.' }]
    const { input } = make({ specs: box, values: { on: '1' } })
    expect(input('On')).toBeChecked()
    expect(document.body).toHaveTextContent('Be on.')
  })

  it('leaves a bool without help blank, and a missing bool value unchecked', () => {
    const box: ParamSpec[] = [{ name: 'on', label: 'On', type: 'bool', required: false }]
    const { input } = make({ specs: box, values: {} })
    expect(input('On')).not.toBeChecked()
    expect(document.querySelector('.field-help')?.textContent).toBe(' ')
  })
})
