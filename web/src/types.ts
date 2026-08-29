// Type definitions mirroring the JSON payload from `GET /api/dataset`
// (see steam_backlog_enforcer/_web_dataset.py). Hour fields use -1 for
// "no data", matching the cache convention.

export interface WebGame {
  app_id: number
  name: string
  completion_pct: number
  playtime_minutes: number
  rush_hours: number
  leisure_hours: number
  worst_hours: number
  count_comp: number
  comp_100_count: number
  hltb_game_id: number
  protondb_tier: string
  protondb_trending_tier: string
  protondb_score: number
}

export interface WebStateInfo {
  current_app_id: number | null
  current_game_name: string
  games_done: number
  games_done_since_start: number
  days_elapsed: number
  enforcement_started_at: string
  pace_games_per_day: number
}

export interface WebDefaults {
  min_comp_100_polls: number
  min_count_comp: number
  min_confidence_sum: number
  min_playable_tier: string
  hours_per_day_presets: number[]
}

export interface DefaultSummary {
  qualifying: number
  rush_total: number
  leisure_total: number
  worst_total: number
}

export interface PaceVsHLTB {
  calibration_count: number
  /** -1 = no data */
  ratio_vs_rush: number
  /** -1 = no data */
  ratio_vs_leisure: number
  /** Position between rush (0) and leisure (1) speed; -1 = unknown */
  interpolation_t: number
  player_style: 'faster_than_rush' | 'rush_to_leisure' | 'slower_than_leisure' | 'unknown'
}

export interface WebDataset {
  games: WebGame[]
  state: WebStateInfo
  defaults: WebDefaults
  default_summary: DefaultSummary
  pace_vs_hltb: PaceVsHLTB | null
  generated_at: string
}

// Which time model drives the headline finish-date and the timeline chart.
export type EstimateBasis = 'rush' | 'leisure' | 'worst' | 'pace'

// How the ProtonDB compatibility filter behaves.
//  - 'playable': faithful port of the CLI's compound `is_playable` rule.
//  - 'minTier':  simple "best available tier must be at least X".
export type ProtonMode = 'playable' | 'minTier'

export type PlaytimeMode = 'all' | 'started' | 'untouched'

export interface Filters {
  // HLTB confidence thresholds (CLI defaults: 15 / 3 / 18).
  minCountComp: number
  minComp100: number
  minConfidenceSum: number
  // ProtonDB compatibility.
  protonMode: ProtonMode
  protonMinTier: string
  protonTreatMissingAsPass: boolean
  // Time budget + which model is primary.
  dailyHours: number
  basis: EstimateBasis
  // Extra filters.
  maxHoursPerGame: number // 0 = no cap
  playtimeMode: PlaytimeMode
  includeNoData: boolean
  fallbackHours: number
  // Manual exclusions (Steam app IDs) and table search.
  excluded: ReadonlySet<number>
  search: string
  // Target-date planner ('' = disabled), ISO yyyy-mm-dd.
  targetDate: string
}

/** Why the budget state file could or could not be read. */
export type BudgetStateStatus = 'ok' | 'missing' | 'denied' | 'corrupt'

export interface BudgetToday {
  gaming_day: string
  day_starts_at: string
  seconds_used: number
  budget_seconds: number
  seconds_remaining: number
  /** 0..1, already clamped by the backend. */
  fraction_used: number
  blocked: boolean
  /** Epoch seconds; 0 means the cutoff has not engaged. */
  blocked_at: number
  /** Seconds-remaining at which the next warning fires; null when none left. */
  next_warning_seconds: number | null
  warned_seconds: number[]
}

export interface BudgetProcess {
  pid: number
  name: string
}

export interface BudgetSession {
  available: boolean
  /** ISO-8601 timestamp the daemon recorded; may be minutes old. */
  observed_at: string
  state: string
  reason: string
  causes: string[]
  idle_seconds: number | null
  screen_held: boolean | null
  game_name: string
  qualifying_count: number
  processes: BudgetProcess[]
}

export interface BudgetHistoryDay {
  day: string
  seconds: number
}

export interface BudgetRules {
  budget_seconds: number
  enforcement: boolean
  counts_launchers: boolean
  engagement_gate: boolean
  idle_grace_seconds: number
  require_game_focus: boolean
  warn_at: number[]
  demo: boolean
  masked_launchers: string[]
}

export interface BudgetSnapshot {
  ok: boolean
  readable: boolean
  state_status: BudgetStateStatus
  /** Human sentence explaining a non-ok status; null when readable. */
  error: string | null
  today: BudgetToday | null
  session: BudgetSession
  history: BudgetHistoryDay[]
  rules: BudgetRules
}

export type TabId = 'planner' | 'budget'
