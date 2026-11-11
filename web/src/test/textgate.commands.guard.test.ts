// Guard test (textgate-rework R6): command buttons and cards paint a glyph,
// never their label, description or lock reason; those are spoken only.

import { describe, expect, it, vi } from 'vitest'
import { mount, stubApi } from './harness'
import { makeSpec } from './fixtures'
import { visibleWords } from './visibleWords'
import '../commands/commandButton'

describe('textgate guard: commands', () => {
  it('a labelled command button paints no words', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('done')] })
    const el = mount('<command-button name="done" label="I got an achievement"></command-button>')
    await vi.waitFor(() => {
      expect(el.querySelector('button')).toHaveAttribute('aria-disabled', 'false')
    })
    expect(visibleWords(el)).toEqual([])
  })

  it('a view command link paints no words', async () => {
    stubApi({ 'GET /api/commands': [makeSpec('status', { kind: 'view' })] })
    const el = mount('<command-button name="status"></command-button>')
    await vi.waitFor(() => {
      expect(el.querySelector('a')).not.toBeNull()
    })
    expect(visibleWords(el)).toEqual([])
  })

  it('a locked, privileged countdown card paints no words', async () => {
    const friction = { phrase_template: 'x', countdown_seconds: 300 }
    stubApi({
      'GET /api/commands': [makeSpec('gaming-reset', { privileged: true, friction, locked_reason: 'Locked by a pick' })],
    })
    const el = mount('<command-card name="gaming-reset" label="Reset today…"></command-card>')
    await vi.waitFor(() => {
      expect(el.querySelector('article')).toHaveClass('locked')
    })
    expect(visibleWords(el)).toEqual([])
  })
})
