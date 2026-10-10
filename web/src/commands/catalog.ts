// Where each command lives in the UI, and client-side phrase previews.
// `satisfies Record<CommandName, …>` makes the compiler prove all 25 CLI
// commands have a home — adding one to the contract without placing it fails
// the build.

import type { CommandName, CommandSpec, InstalledGame } from '../api/contract'

export type SectionPath =
  | '/'
  | '/backlog'
  | '/gaming'
  | '/library'
  | '/picks'
  | '/store'
  | '/system'
  | '/setup'

export const COMMAND_HOME = {
  status: '/',
  list: '/backlog',
  stats: '/backlog',
  installed: '/library',
  'gaming-status': '/gaming',
  check: '/picks',
  scan: '/picks',
  done: '/picks',
  pick: '/picks',
  'pick-manual': '/picks',
  'abandon-pick': '/picks',
  install: '/library',
  uninstall: '/library',
  hide: '/library',
  unhide: '/library',
  'buy-dlc': '/store',
  unblock: '/store',
  'add-exception': '/store',
  'block-gaming': '/gaming',
  reset: '/system',
  setup: '/setup',
  enforce: '/system',
  'gaming-reset': '/gaming',
  'gaming-unblock': '/gaming',
  serve: '/system',
  'restore-backup': '/system',
} as const satisfies Record<CommandName, SectionPath>

/** Title-case label for buttons and the palette (`pick-manual` → `Pick manual`). */
export function commandLabel(name: CommandName): string {
  const s = name.replace(/-/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Mirror of `_friction.phrase_matches`: only surrounding whitespace is forgiven. */
export function phraseMatches(expected: string, typed: string): boolean {
  return typed.trim() === expected
}

export interface PhraseContext {
  gameName: (appId: number) => string | null
  installed: InstalledGame[] | null
}

export interface FilledPhrase {
  text: string
  /** Placeholders the UI could not resolve; the phrase cannot be typed yet. */
  missing: string[]
}

/**
 * Fill a FrictionSpec template from the form's params plus what the UI
 * knows. The server fills and checks its own copy — this is only so the user
 * sees the exact sentence before submitting.
 */
export function fillPhrase(
  template: string,
  params: Record<string, number | string>,
  ctx: PhraseContext,
): FilledPhrase {
  const missing: string[] = []
  const text = template.replace(/\{(\w+)\}/g, (whole, key: string) => {
    let value: string | null = null
    if (key in params && params[key] !== '') value = String(params[key])
    else if (key === 'game_name' && params.app_id !== undefined) value = ctx.gameName(Number(params.app_id))
    else if (key === 'count' && ctx.installed) {
      value = String(ctx.installed.filter((g) => !g.assigned && !g.protected).length)
    }
    if (value === null) missing.push(key)
    return value ?? whole
  })
  return { text, missing }
}

export function findCommand(list: CommandSpec[] | undefined, name: CommandName): CommandSpec | undefined {
  return list?.find((c) => c.name === name)
}
