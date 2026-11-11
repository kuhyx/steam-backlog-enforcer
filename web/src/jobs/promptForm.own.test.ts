import { describe, expect, it } from 'vitest'
import type { PromptEvent } from './hub'
import { promptForm } from './promptForm'

const choice = (options: { value: string; label: string }[]): PromptEvent => ({
  seq: 1, ts: 't', type: 'prompt', prompt_id: 'q1', kind: 'choice', message: 'Which one?', options,
})

describe('choice prompt own-game escape', () => {
  it('paints the escape as a glyph and speaks its label; game names stay plain text', () => {
    const form = promptForm('j', choice([{ value: 'a', label: 'Alpha' }, { value: 'own', label: 'Pick my own game' }]))
    document.body.append(form)
    const own = form.querySelector('[data-value=own] .choice-label')
    expect(own?.querySelector('[aria-hidden="true"]')?.textContent).toBe('🗂️')
    expect(own?.querySelector('.sr-only')?.textContent).toBe('Pick my own game')
    expect(form.querySelector('[data-value=a] .choice-label')?.textContent).toBe('Alpha')
  })
})
