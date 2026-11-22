// Completeness gate for the icon words: every icon the UI paints comes from
// the registry (icons/registry.json), so the /words picker covers the whole
// UI. This scans the source, not a rendered page: a pictograph or an icon
// symbol typed as a literal in any non-test file is an unregistered icon.
// Comments are ignored; the picker's own controls and the palette's key
// hints are the only allowed literals, named below.

import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ICONS } from './registry'

const SRC = join(import.meta.dirname, '..')

/** Pictographs, plus the symbol icons the UI paints (Σ ∅ ↺ ✕ ↵ ▲ ▼ ∞ and arrows). */
const ICON_LITERAL = /\p{Extended_Pictographic}|[Σ∅↺✕↵▲▼∞←→↑↓]|'×'|\u{FE0F}/u

/** The /words picker's own controls and keyboard hints: text, not UI icons. */
const ALLOWED = ["'← back'", "'forward →'", "'↑↓ · ⏎ · ⎋'", "'↑↓ to move · Enter to run · Esc to close'","{ class: 'm0' }, '✅')"]

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: 'utf8' })
    .map((f) => join(dir, f))
    .filter((f) => /\.(ts|astro)$/.test(f) && !f.endsWith('.test.ts') && !f.includes(`${join(SRC, 'test')}/`))
}

function code(text: string): string {
  const noBlocks = text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '))
  return noBlocks.replace(/(^|\s)\/\/.*$/gm, '$1')
}

/** `file:line` of every line that paints an icon literal. */
function unregistered(): string[] {
  const hits: string[] = []
  for (const file of sourceFiles(SRC)) {
    const lines = code(readFileSync(file, 'utf8')).split('\n')
    lines.forEach((line, i) => {
      const bare = ALLOWED.reduce((s, a) => s.split(a).join(''), line)
      if (ICON_LITERAL.test(bare)) hits.push(`${relative(SRC, file)}:${i + 1}`)
    })
  }
  return hits
}

describe('icon words cover the whole UI', () => {
  it('no source file paints an icon outside the registry', () => {
    const hits = unregistered()
    expect(hits, `${hits.length} unregistered icon sites`).toEqual([])
  })

  it('the first 47 registry entries are the pass-1 icons (all answered but cmd.re-block and cmd.repair-ghosts), then the rest', () => {
    const ids = ICONS.map((e) => e.id)
    expect(ids.slice(0, 47).filter((id) => /^(nav|palette|cmd|job\.state|notice)\./.test(id))).toHaveLength(47)
    expect(ids[46]).toBe('notice.danger')
  })
})
