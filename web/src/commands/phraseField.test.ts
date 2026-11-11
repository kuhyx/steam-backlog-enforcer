import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PhraseField } from './phraseField'

function make(over: { value?: string; label?: string; autofocus?: boolean } = {}) {
  const onChange = vi.fn()
  const field = new PhraseField({ phrase: 'reset it', onChange, ...over })
  document.body.append(field.el)
  return { field, onChange, input: field.input, status: () => field.el.querySelector('[aria-live]') }
}

describe('PhraseField', () => {
  it('counts characters while the prefix is right', async () => {
    const { input, status, onChange } = make()
    expect(status()).toHaveTextContent('0 of 8 characters')
    await userEvent.type(input, 'res')
    expect(status()).toHaveTextContent('3 of 8 characters')
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(input.className).toBe('input mono')
    expect(onChange).toHaveBeenLastCalledWith('res')
  })

  it('marks a mismatch', async () => {
    const { input, status } = make()
    await userEvent.type(input, 'rx')
    expect(status()).toHaveTextContent(/Does not match/)
    expect(status()).toHaveClass('text-danger')
    expect(input).toHaveClass('input-bad')
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('confirms the full phrase, ignoring surrounding whitespace', () => {
    const { input, status, field } = make({ value: ' reset it ' })
    expect(status()).toHaveTextContent('Matches.')
    expect(status()).toHaveClass('text-success')
    expect(input).toHaveClass('input-ok')
    expect(field.value).toBe(' reset it ')
  })

  it('colours each target character by whether it was typed right', () => {
    const { field } = make({ value: 'rx' })
    const spans = [...field.el.querySelectorAll('.phrase-target span')]
    expect(spans).toHaveLength(8)
    expect(spans[0]).toHaveClass('ok')
    expect(spans[1]).toHaveClass('bad')
    expect(spans[2]).not.toHaveClass('ok')
    expect(spans[2]).not.toHaveClass('bad')
  })

  it('blocks paste and drop', () => {
    const { input } = make()
    expect(input.dispatchEvent(new Event('paste', { cancelable: true }))).toBe(false)
    expect(input.dispatchEvent(new Event('drop', { cancelable: true }))).toBe(false)
  })

  it('labels the input, shows the phrase to screen readers, and can ask for focus', () => {
    const { field, input } = make({ autofocus: true })
    expect(field.el.querySelector('label')).toHaveTextContent('Type the phrase to confirm')
    expect(field.el.querySelector('label')).toHaveAttribute('for', input.id)
    expect(field.el.querySelector('label .sr-only')).toHaveTextContent('Type the phrase to confirm')
    expect(field.el.querySelector('label [aria-hidden]')).toHaveTextContent('⌨️')
    expect(field.el.querySelector('p.sr-only')).toHaveTextContent('Phrase: reset it')
    expect(input).toHaveAttribute('autofocus')
    expect(make({ label: 'Again' }).field.el.querySelector('label')).toHaveTextContent('Again')
    expect(make().input).not.toHaveAttribute('autofocus')
  })
})
