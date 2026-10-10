// `GET /api/commands` for the mock: the server-driven catalog, mirroring
// `steam_backlog_enforcer/_friction.py` and the CLI's lock-exempt sets.

import type { CommandName, CommandSpec, ParamSpec } from '../src/api/contract.ts'
import { world } from './world.ts'

type Base = Omit<CommandSpec, 'locked_reason'>

const APP_ID: ParamSpec = { name: 'app_id', label: 'Game', type: 'app_id', required: true }
const MINUTES: ParamSpec = {
  name: 'minutes', label: 'Minutes', type: 'int', required: true, min: 1, max: 30, default: 15,
  help: 'Hard cap: 30 minutes.',
}

function spec(
  name: CommandName,
  description: string,
  category: CommandSpec['category'],
  kind: CommandSpec['kind'],
  extra: Partial<Base> = {},
): Base {
  return {
    name, description, category, kind, params: [], friction: null,
    privileged: false, mutating: kind === 'job', cancellable: false, ...extra,
  }
}

const phrase = (phrase_template: string, countdown_seconds?: number) =>
  countdown_seconds ? { phrase_template, countdown_seconds } : { phrase_template }

export const BASE: Base[] = [
  spec('status', 'Show current status', 'backlog', 'view', { view_endpoint: '/api/status' }),
  spec('list', 'List games from snapshot', 'backlog', 'view', { view_endpoint: '/api/dataset' }),
  spec('stats', 'Show backlog completion-time estimates', 'backlog', 'view', { view_endpoint: '/api/stats' }),
  spec('installed', 'List installed games', 'library', 'view', { view_endpoint: '/api/installed' }),
  spec('gaming-status', "Show today's gaming time and block state", 'gaming', 'view', {
    view_endpoint: '/api/budget',
  }),
  spec('check', 'Check assigned game for a new achievement', 'backlog', 'job', { mutating: false }),
  spec('scan', 'Scan library & assign a game', 'backlog', 'job', { cancellable: true }),
  spec('done', 'Move on after a new achievement, pick next', 'backlog', 'job'),
  spec('pick', 'Manually pick your next game from candidates', 'backlog', 'job', { cancellable: true }),
  spec('pick-manual', 'Pick a game by app_id, lock enforcer for 14 days', 'backlog', 'job', {
    params: [APP_ID], friction: phrase('lock in {game_name}'),
  }),
  spec('abandon-pick', 'Undo a manual pick at any time', 'backlog', 'job', {
    params: [APP_ID], friction: phrase('abandon {game_name}'),
  }),
  spec('install', 'Install the assigned game', 'library', 'job', { cancellable: true }),
  spec('uninstall', 'Uninstall all non-assigned games', 'library', 'job', {
    friction: phrase('uninstall {count} games'),
  }),
  spec('hide', 'Hide all non-assigned games in library', 'library', 'job'),
  spec('unhide', 'Unhide all games in library', 'library', 'job'),
  spec('buy-dlc', 'Unblock the store to buy a game/DLC', 'store', 'job', {
    params: [MINUTES], friction: phrase('unblock the store for {minutes} minutes'), privileged: true,
  }),
  spec('unblock', 'Unblock the store for a few minutes', 'store', 'job', {
    params: [MINUTES], friction: phrase('unblock the store for {minutes} minutes'), privileged: true,
  }),
  spec('add-exception', 'Whitelist a game immediately (phrase + reason)', 'store', 'job', {
    params: [APP_ID, { name: 'reason', label: 'Reason', type: 'string', required: true, help: 'Why this game must be allowed.' }],
    friction: phrase('request exception for {game_name}'),
  }),
  spec('block-gaming', 'Block ALL gaming for N days, no in-app undo', 'gaming', 'job', {
    params: [{ name: 'days', label: 'Days', type: 'int', required: true, min: 1, max: 365, default: 1 }],
    friction: phrase('block all gaming for {days} days'), privileged: true,
  }),
  spec('reset', 'Reset all state (a timestamped backup is taken first)', 'system', 'job', {
    friction: phrase('wipe all enforcer state'),
  }),
  spec('setup', 'First-time setup: Steam API key and Steam ID', 'system', 'screen'),
  spec('enforce', 'Run enforcer: block, uninstall, kill, hide (--demo for a 60s budget)', 'system', 'screen', {
    params: [{
      name: 'demo', label: 'Demo mode (1 = 60-second budget)', type: 'int', required: false, default: 0, min: 0, max: 1,
    }],
    privileged: true, cancellable: true,
  }),
  spec('gaming-reset', "Reset today's gaming counter", 'gaming', 'job', {
    friction: phrase("reset today's gaming budget", 300), privileged: true,
  }),
  spec('gaming-unblock', 'Force-release playtime bind mounts (recovery hatch)', 'gaming', 'job', {
    friction: phrase('force release playtime mounts'), privileged: true,
  }),
  spec('serve', 'The web UI server: health, stale check and restart', 'system', 'screen'),
]

const MANUAL_EXEMPT = new Set<CommandName>([
  'done', 'check', 'status', 'enforce', 'setup', 'serve', 'abandon-pick', 'pick-manual',
  'gaming-status', 'gaming-unblock', 'gaming-reset',
])
const TOTAL_EXEMPT = new Set<CommandName>(['status', 'enforce', 'gaming-status', 'gaming-unblock', 'serve'])

export function lockedReason(name: CommandName): string | null {
  if (world.lock === 'total' && !TOTAL_EXEMPT.has(name)) {
    return 'Total gaming block is active (4 days left). Nothing can shorten it.'
  }
  if (world.lock === 'manual' && !MANUAL_EXEMPT.has(name)) {
    return 'Manual pick lock: earn one new achievement in Hades, then run "done" or "check".'
  }
  return null
}

export function catalog(): CommandSpec[] {
  const countdown = world.countdownSeconds
  return BASE.map((s) => ({
    ...s,
    friction:
      s.friction?.countdown_seconds !== undefined ? { ...s.friction, countdown_seconds: countdown } : s.friction,
    locked_reason: lockedReason(s.name),
  }))
}

export function findSpec(name: string): CommandSpec | undefined {
  return catalog().find((s) => s.name === name)
}
