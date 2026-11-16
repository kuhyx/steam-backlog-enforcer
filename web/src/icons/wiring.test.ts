// The registered call sites look their icon up by id: a ledger word shows
// right of the icon, a chosen alternative replaces the default glyph.

import { describe, expect, it } from 'vitest'
import { commandIcon } from '../commands/catalog'
import { commandButton } from '../commands/commandButton'
import { stateBadge } from '../jobs/progress'
import { NAV } from '../shell/nav'
import { useIcons } from '../test/iconLedger'
import { notice } from '../ui/build'
import { isIconId } from './registry'

describe('registered call sites', () => {
  it('a command button paints the word right of its icon, label still spoken', () => {
    useIcons({ 'cmd.done': { word: 'trophy', glyph: '🥇' } })
    const btn = commandButton({ name: 'done', label: 'I got an achievement' })
    const icon = btn.querySelector('.cmd-icon')
    expect(icon?.textContent).toBe('🥇')
    expect(icon?.nextElementSibling).toHaveClass('icon-word')
    expect(icon?.nextElementSibling?.textContent).toBe('Trophy')
    expect(btn).toHaveAttribute('aria-label', 'I got an achievement')
  })

  it('a command button without a word is unchanged', () => {
    const btn = commandButton({ name: 'scan' })
    expect(btn.querySelector('.cmd-icon')?.textContent).toBe('🔎')
    expect(btn.querySelector('.icon-word')).toBeNull()
  })

  it('a notice paints its tone word right of the tone icon', () => {
    useIcons({ 'notice.warning': { word: 'careful' } })
    const el = notice('warning', null)
    const icon = el.querySelector('.notice-icon')
    expect(icon?.nextElementSibling?.textContent).toBe('Careful')
    expect(icon?.parentElement).toHaveClass('has-word')
  })

  it('a job state badge paints its word and keeps its aria-label', () => {
    useIcons({ 'job.state.running': { word: 'busy', glyph: '⚡' } })
    const el = stateBadge('running')
    expect(el.querySelector('.pill-icon')?.textContent).toBe('⚡')
    expect(el.querySelector('.icon-word')?.textContent).toBe('Busy')
    expect(el).toHaveAttribute('aria-label', 'running')
  })

  it('nav entries and commands are looked up by id', () => {
    for (const n of NAV) expect(isIconId(n.icon)).toBe(true)
    expect(commandIcon('gaming-status')).toBe('cmd.gaming-status')
  })

})
