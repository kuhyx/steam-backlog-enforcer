// Mutable world state behind the mock API. Jobs mutate it, so the UI sees
// the effect of `done`, `uninstall`, `unblock` … after the job finishes.

import type {
  DaemonState,
  DaemonStatus,
  InstalledGame,
  LibraryPayload,
  ServerHealth,
  SetupStatus,
  StateBackup,
  StatsPayload,
  StatusPayload,
} from '../src/api/contract.ts'
import type { WebDataset } from '../src/types.ts'
import { GAMES, hash, makeInstalled, makeWebGame, nameOf } from './games.ts'

export type LockMode = 'none' | 'manual' | 'total'

const iso = (ms: number) => new Date(ms).toISOString()
const DAY = 86_400_000

export interface World {
  configured: boolean
  steamId: string | null
  lock: LockMode
  daemon: DaemonState
  daemonStartedAt: number
  restartAvailableAt: number | null
  serverStartedAt: number
  stale: boolean
  countdownSeconds: number
  currentAppId: number | null
  finished: number[]
  storeBlockedUntil: number | null
  totalBlockUntil: number | null
  manualPicks: { app_id: number; picked_at: number }[]
  installed: InstalledGame[]
  backups: StateBackup[]
  journal: string[]
}

const now = Date.now()

export const world: World = {
  configured: true,
  steamId: '76561198012345678',
  lock: 'none',
  daemon: 'running',
  daemonStartedAt: now - 3 * 3_600_000,
  restartAvailableAt: null,
  serverStartedAt: now - 40 * 60_000,
  stale: false,
  countdownSeconds: 300,
  currentAppId: 1145360,
  finished: [504230, 391540, 1055540, 383870, 501300, 683320, 304430],
  storeBlockedUntil: null,
  totalBlockUntil: null,
  manualPicks: [],
  installed: makeInstalled(1145360),
  backups: [
    { id: '20261009-221504', created_at: iso(now - DAY), reason: 'before reset', size_bytes: 48_211 },
    { id: '20261002-090112', created_at: iso(now - 8 * DAY), reason: 'nightly', size_bytes: 47_930 },
    { id: '20260925-090044', created_at: iso(now - 15 * DAY), reason: 'nightly', size_bytes: 45_118 },
  ],
  journal: [],
}

export function journal(line: string): void {
  const stamp = new Date().toTimeString().slice(0, 8)
  world.journal.push(`${stamp} steam-backlog-enforcer[4123]: ${line}`)
  if (world.journal.length > 200) world.journal.splice(0, world.journal.length - 200)
}

for (const line of [
  'enforce loop started (tick 3s)',
  'store blocked via iptables (4 rules)',
  'library hidden: 512 apps, 1 visible (Hades)',
  'playtime: Hades engaged, 2h10m of 3h used',
]) {
  journal(line)
}

export function gameName(appId: number): string {
  return nameOf(appId) ?? `App ${appId}`
}

export function status(): StatusPayload {
  const t = Date.now()
  const totalActive = world.totalBlockUntil !== null && world.totalBlockUntil > t
  return {
    current_app_id: world.currentAppId,
    current_game_name: world.currentAppId === null ? null : gameName(world.currentAppId),
    finished_count: world.finished.length,
    store_blocked: world.storeBlockedUntil === null || world.storeBlockedUntil < t,
    installed_count: world.installed.length,
    assigned_game_installed: world.installed.some((g) => g.assigned),
    total_block: {
      active: totalActive,
      days_remaining: totalActive ? Math.ceil((world.totalBlockUntil! - t) / DAY) : 0,
      until: totalActive ? iso(world.totalBlockUntil!) : null,
    },
    manual_pick_locked: world.lock === 'manual' || world.manualPicks.length > 0,
    manual_picks: world.manualPicks.map((p) => ({
      app_id: p.app_id,
      name: gameName(p.app_id),
      age_days: Math.floor((t - p.picked_at) / DAY),
    })),
  }
}

export function dataset(): WebDataset {
  const games = GAMES.filter(([id]) => !world.finished.includes(id)).map(([id, name]) =>
    makeWebGame(id, name),
  )
  const summary = { qualifying: games.length - 6, rush_total: 812, leisure_total: 1460, worst_total: 1930 }
  return {
    games,
    state: {
      current_app_id: world.currentAppId,
      current_game_name: world.currentAppId === null ? '' : gameName(world.currentAppId),
      games_done: world.finished.length,
      games_done_since_start: world.finished.length,
      days_elapsed: 143,
      enforcement_started_at: '2026-05-20T08:00:00+00:00',
      pace_games_per_day: Math.round((world.finished.length / 143) * 1000) / 1000,
    },
    defaults: {
      min_comp_100_polls: 3,
      min_count_comp: 15,
      min_confidence_sum: 18,
      min_playable_tier: 'gold',
      hours_per_day_presets: [1, 2, 3, 4, 6],
    },
    default_summary: summary,
    pace_vs_hltb: {
      calibration_count: world.finished.length,
      ratio_vs_rush: 1.12,
      ratio_vs_leisure: 0.62,
      interpolation_t: 0.18,
      player_style: 'rush_to_leisure',
    },
    generated_at: new Date().toISOString(),
  }
}

export function stats(): StatsPayload {
  const d = dataset()
  return { default_summary: d.default_summary, pace_vs_hltb: d.pace_vs_hltb }
}

export function setupStatus(): SetupStatus {
  return { configured: world.configured, has_api_key: world.configured, steam_id: world.steamId }
}

export function daemonStatus(): DaemonStatus {
  const reachable = world.daemon !== 'unreachable'
  const t = Date.now()
  return {
    state: world.daemon,
    started_at: reachable ? iso(world.daemonStartedAt) : null,
    pid: reachable ? 4123 : null,
    journal_tail: reachable ? world.journal.slice(-60) : [],
    restart_available_at:
      world.restartAvailableAt !== null && world.restartAvailableAt > t ? iso(world.restartAvailableAt) : null,
  }
}

export function serverHealth(): ServerHealth {
  return { stale: world.stale, started_at: iso(world.serverStartedAt), version: '0.42.0+mock' }
}

/** Background chatter so the journal tail visibly moves. */
setInterval(() => {
  if (world.daemon !== 'running') return
  const lines = [
    'tick: Hades engaged, budget ok',
    'hosts guard: /etc/hosts unchanged',
    'library hider: 0 changes',
    'store blocker: rules intact',
  ]
  journal(lines[Math.floor(Date.now() / 5000) % lines.length])
}, 5000).unref()

/** `GET /api/library`: every fixture game, with the real server's reasons. */
export function library(): LibraryPayload {
  const installed = new Set(world.installed.map((g) => g.app_id))
  return {
    games: GAMES.map(([id, name]) => {
      const h = hash(id)
      const done = world.finished.includes(id)
      const total = h % 11 === 0 ? 0 : 10 + (h % 60)
      const unlocked = done ? total : h % 4 === 0 ? h % total || 0 : 0
      const skipped = !done && total > 0 && h % 9 === 0
      return {
        app_id: id,
        name,
        achievements_total: total,
        achievements_unlocked: total ? unlocked : 0,
        hltb_hours: h % 13 === 0 ? null : 4 + (h % 60),
        playtime_minutes: h % 3 === 0 ? h % 900 : 0,
        last_played: h % 3 === 0 ? 1_790_000_000 - (h % 5_000_000) : null,
        installed: installed.has(id),
        assigned: id === world.currentAppId,
        ineligible_reason: total === 0 ? 'No achievements' : done ? 'Already 100% complete' : skipped ? 'Skipped until 2026-10-17' : null,
      }
    }),
  }
}
