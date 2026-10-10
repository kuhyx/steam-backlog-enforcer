// Frozen contract between the Python web server and the React app.
// Jobs, prompts, pending actions and errors live in jobContract.ts.
// Prose spec: DOCS-web-control-api.md at the repo root. Change both together.

import type { BudgetSnapshot, DefaultSummary, WebDataset } from '../types'

export type CommandName =
  | 'status'
  | 'list'
  | 'stats'
  | 'installed'
  | 'gaming-status'
  | 'check'
  | 'scan'
  | 'done'
  | 'pick'
  | 'pick-manual'
  | 'abandon-pick'
  | 'install'
  | 'uninstall'
  | 'hide'
  | 'unhide'
  | 'buy-dlc'
  | 'unblock'
  | 'add-exception'
  | 'block-gaming'
  | 'reset'
  | 'setup'
  | 'enforce'
  | 'gaming-reset'
  | 'gaming-unblock'
  | 'serve'
  /** Job spawned by `POST /api/backups/{id}/restore`, not a CLI command. */
  | 'restore-backup'

/** How the UI surfaces a command. */
export type CommandKind =
  /** Read-only data, rendered from a GET endpoint (`view_endpoint`). */
  | 'view'
  /** Runs as a job with live progress. */
  | 'job'
  /** Has a dedicated screen (setup wizard, daemon, server health). */
  | 'screen'

export type CommandCategory = 'backlog' | 'library' | 'gaming' | 'store' | 'system'

export interface ParamSpec {
  name: string
  label: string
  type: 'int' | 'string' | 'app_id'
  required: boolean
  min?: number
  max?: number
  default?: number | string
  help?: string
}

export interface FrictionSpec {
  /**
   * Template with `{param}` / `{game_name}` / `{count}` placeholders, filled
   * in by the server in `PendingAction.phrase` or a `phrase` prompt. The
   * server re-checks the typed text; the UI only helps.
   */
  phrase_template: string
  /** Seconds of armed countdown with heartbeats before commit is allowed. */
  countdown_seconds?: number
}

export interface CommandSpec {
  name: CommandName
  description: string
  category: CommandCategory
  kind: CommandKind
  params: ParamSpec[]
  friction: FrictionSpec | null
  /** Executed by the root daemon over the control socket. */
  privileged: boolean
  /** Mutates state; at most one mutating job runs at a time. */
  mutating: boolean
  cancellable: boolean
  /** Present when the manual-pick or total-block lock forbids it right now. */
  locked_reason: string | null
  view_endpoint?: string
}

// ---- views ---------------------------------------------------------------

export interface ManualPickInfo {
  app_id: number
  name: string
  age_days: number
}

export interface StatusPayload {
  current_app_id: number | null
  current_game_name: string | null
  finished_count: number
  store_blocked: boolean
  installed_count: number
  assigned_game_installed: boolean
  total_block: { active: boolean; days_remaining: number; until: string | null }
  manual_pick_locked: boolean
  manual_picks: ManualPickInfo[]
}

export interface StatsPayload {
  default_summary: DefaultSummary
  pace_vs_hltb: WebDataset['pace_vs_hltb']
}

export interface InstalledGame {
  app_id: number
  name: string
  size_bytes: number
  assigned: boolean
  protected: boolean
}

export interface InstalledPayload {
  games: InstalledGame[]
}

/** One owned game in the library browser (`GET /api/library`). */
export interface LibraryGame {
  app_id: number
  name: string
  /** 0 when the scan has no achievement data for it. */
  achievements_total: number
  achievements_unlocked: number
  /** Completionist hours (HLTB), null when unknown. */
  hltb_hours: number | null
  playtime_minutes: number
  /** Unix seconds of the last session, null when never played. */
  last_played: number | null
  installed: boolean
  /** The assignment or an active manual pick. */
  assigned: boolean
  /** Why "pick my own game" refuses it; null when it may be picked. */
  ineligible_reason: string | null
}

export interface LibraryPayload {
  games: LibraryGame[]
}

export interface SetupStatus {
  configured: boolean
  has_api_key: boolean
  steam_id: string | null
}

export interface SetupRequest {
  steam_api_key: string
  steam_id: string
}

export type DaemonState = 'running' | 'restarting' | 'unreachable'

export interface DaemonStatus {
  state: DaemonState
  started_at: string | null
  pid: number | null
  journal_tail: string[]
  /** ISO time before which `restart` is rate-limited, or null. */
  restart_available_at: string | null
}

export interface ServerHealth {
  stale: boolean
  started_at: string
  version: string
}

export interface StateBackup {
  id: string
  created_at: string
  reason: string
  size_bytes: number
}

export const ENDPOINTS = {
  dataset: '/api/dataset',
  budget: '/api/budget',
  status: '/api/status',
  stats: '/api/stats',
  installed: '/api/installed',
  library: '/api/library',
  /** Portrait cover JPEG; 404 when there is none (draw a title tile). */
  art: (appId: number) => `/api/art/${appId}`,
  commands: '/api/commands',
  setup: '/api/setup',
  daemon: '/api/daemon',
  server: '/api/server',
  serverRestart: '/api/server/restart',
  backups: '/api/backups',
  backupRestore: (id: string) => `/api/backups/${id}/restore`,
  jobs: '/api/jobs',
  job: (id: string) => `/api/jobs/${id}`,
  jobEvents: (id: string) => `/api/jobs/${id}/events`,
  jobAnswer: (id: string) => `/api/jobs/${id}/answer`,
  jobCancel: (id: string) => `/api/jobs/${id}/cancel`,
  pendingHeartbeat: (id: string) => `/api/pending/${id}/heartbeat`,
  pendingCommit: (id: string) => `/api/pending/${id}/commit`,
  pending: (id: string) => `/api/pending/${id}`,
} as const

export const TOKEN_META = 'sbe-token'
export const TOKEN_HEADER = 'X-SBE-Token'

export type { BudgetSnapshot, WebDataset }
