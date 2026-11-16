import { describe, expect, it } from 'vitest'
import type { JobState } from '../api/jobContract'
import { COMMAND_HOME, commandIcon } from '../commands/catalog'
import { NAV } from '../shell/nav'
import type { Tone } from '../ui/build'
import { ICONS, iconEntry, isIconId } from './registry'

const JOB_STATES: JobState[] = ['queued', 'running', 'waiting_input', 'succeeded', 'failed', 'cancelled']
const TONES: Tone[] = ['info', 'success', 'warning', 'danger']

describe('icon registry', () => {
  it('registers exactly this pass: 8 nav, the palette, 26 commands, 6 job states, 4 tones', () => {
    const ids = ICONS.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toHaveLength(8 + 1 + 26 + 6 + 4)
    for (const n of NAV) expect(isIconId(n.icon)).toBe(true)
    expect(isIconId('palette.open')).toBe(true)
    for (const name of Object.keys(COMMAND_HOME) as (keyof typeof COMMAND_HOME)[]) {
      expect(isIconId(commandIcon(name))).toBe(true)
    }
    for (const s of JOB_STATES) expect(isIconId(`job.state.${s}`)).toBe(true)
    for (const t of TONES) expect(isIconId(`notice.${t}`)).toBe(true)
  })

  it.each(ICONS.map((e) => [e.id, e] as const))('%s: glyph, name, description, 3 words, 3 alternatives', (_id, e) => {
    expect(e.glyph).not.toBe('')
    expect(e.spoken).not.toBe('')
    expect(e.desc.length).toBeGreaterThan(20)
    expect(e.desc.split(/[.!?](\s|$)/).filter((s) => s.trim()).length).toBeLessThanOrEqual(2)
    expect(e.words).toHaveLength(3)
    expect(new Set(e.words.map((w) => w.toLowerCase())).size).toBe(3)
    for (const w of e.words) expect(w).toMatch(/^\S+$/)
    expect(e.alts).toHaveLength(3)
    expect(new Set([e.glyph, ...e.alts]).size).toBe(4)
  })

  it('keeps every default glyph the UI painted before the registry', () => {
    expect(iconEntry('nav.dashboard').glyph).toBe('🏠')
    expect(iconEntry('palette.open').glyph).toBe('🔍')
    expect(iconEntry('cmd.done').glyph).toBe('🏆')
    expect(iconEntry('cmd.restore-backup').glyph).toBe('🗄️')
    expect(iconEntry('job.state.waiting_input').glyph).toBe('⚠️')
    expect(iconEntry('notice.danger').glyph).toBe('⛔')
  })

  it('tells registered ids from raw glyphs', () => {
    expect(isIconId('cmd.done')).toBe(true)
    expect(isIconId('🏆')).toBe(false)
    expect(isIconId('toString')).toBe(false)
  })
})
