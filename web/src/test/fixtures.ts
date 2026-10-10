// Fixtures for the web-control API shapes (api/contract.ts, jobContract.ts).
// Lives under src/test/, excluded from the app build and from coverage.

import type {
  CommandName,
  CommandSpec,
  InstalledGame,
  LibraryGame,
  StatusPayload,
} from '../api/contract'
import type { Job, PendingAction } from '../api/jobContract'

export function makeSpec(name: CommandName, over: Partial<CommandSpec> = {}): CommandSpec {
  return {
    name,
    description: `Does ${name}.`,
    category: 'backlog',
    kind: 'job',
    params: [],
    friction: null,
    privileged: false,
    mutating: true,
    cancellable: false,
    locked_reason: null,
    ...over,
  }
}

export function makeLibGame(over: Partial<LibraryGame> = {}): LibraryGame {
  return {
    app_id: 1,
    name: 'Game',
    achievements_total: 10,
    achievements_unlocked: 5,
    hltb_hours: 12,
    playtime_minutes: 192,
    last_played: 1_700_000_000,
    installed: false,
    assigned: false,
    ineligible_reason: null,
    ...over,
  }
}

export function makeInstalled(over: Partial<InstalledGame> = {}): InstalledGame {
  return { app_id: 1, name: 'Game', size_bytes: 1024 ** 3, assigned: false, protected: false, ...over }
}

export function makeStatus(over: Partial<StatusPayload> = {}): StatusPayload {
  return {
    current_app_id: 10,
    current_game_name: 'Hollow Knight',
    finished_count: 3,
    store_blocked: true,
    installed_count: 4,
    assigned_game_installed: true,
    total_block: { active: false, days_remaining: 0, until: null },
    manual_pick_locked: false,
    manual_picks: [],
    ...over,
  }
}

export function makeJob(over: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    command: 'scan',
    params: {},
    state: 'running',
    created_at: '2026-10-10T10:00:00Z',
    started_at: '2026-10-10T10:00:01Z',
    ended_at: null,
    exit_code: null,
    progress: null,
    summary: null,
    ...over,
  }
}

export function makePending(over: Partial<PendingAction> = {}): PendingAction {
  return {
    id: 'p1',
    command: 'gaming-reset',
    phrase: 'reset gaming now',
    armed_at: '2026-10-10T10:00:00Z',
    ready_at: '2026-10-10T10:05:00Z',
    heartbeat_interval_seconds: 10,
    ...over,
  }
}
