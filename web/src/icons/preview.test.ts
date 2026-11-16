import { describe, expect, it } from 'vitest'
import { useIcons } from '../test/iconLedger'
import { contextPreview } from './preview'
import type { IconId } from './registry'

describe('contextPreview: the icon as it looks where it is used', () => {
  it.each<[IconId, string, string]>([
    ['nav.gaming', '.nav-link', '🕹️'],
    ['palette.open', '.palette-btn', '⌨️'],
    ['cmd.install', '.btn', '📥'],
    ['job.state.failed', '.pill', '💔'],
    ['notice.info', '.notice', '💡'],
  ])('%s renders inside %s with the chosen glyph and word', (id, shell, alt) => {
    useIcons({ [id]: { word: 'shown here', glyph: alt } })
    const el = contextPreview(id)
    expect(el).toHaveAttribute('inert')
    const host = el.querySelector(shell)
    expect(host).not.toBeNull()
    expect(host?.textContent).toContain(alt)
    expect(host?.querySelector('.icon-word')?.textContent).toBe('Shown here')
  })

  it('shows the default glyph and no word before any choice', () => {
    const el = contextPreview('cmd.install')
    expect(el.textContent).toContain('⬇️')
    expect(el.querySelector('.icon-word')).toBeNull()
  })
})
