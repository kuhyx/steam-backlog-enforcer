// Shared test factories. Lives under src/test/ which is excluded from the
// app build and from coverage.

import type {
  BudgetRules,
  BudgetSession,
  BudgetSnapshot,
  BudgetToday,
  Filters,
  PaceVsHLTB,
  WebDataset,
  WebGame,
  WebStateInfo,
} from '../types'

export function makeGame(over: Partial<WebGame> = {}): WebGame {
  return {
    app_id: 1,
    name: 'Game',
    completion_pct: 0,
    playtime_minutes: 60,
    rush_hours: 10,
    leisure_hours: 20,
    worst_hours: 25,
    count_comp: 20,
    comp_100_count: 5,
    hltb_game_id: 0,
    protondb_tier: 'gold',
    protondb_trending_tier: 'gold',
    protondb_score: 0.8,
    ...over,
  }
}

export function makeFilters(over: Partial<Filters> = {}): Filters {
  return {
    minCountComp: 15,
    minComp100: 3,
    minConfidenceSum: 18,
    protonMode: 'playable',
    protonMinTier: 'gold',
    protonTreatMissingAsPass: true,
    dailyHours: 4,
    basis: 'leisure',
    maxHoursPerGame: 0,
    playtimeMode: 'all',
    includeNoData: false,
    fallbackHours: 20,
    excluded: new Set<number>(),
    search: '',
    targetDate: '',
    ...over,
  }
}

export function makeState(over: Partial<WebStateInfo> = {}): WebStateInfo {
  return {
    current_app_id: null,
    current_game_name: '',
    games_done: 0,
    days_elapsed: 0,
    enforcement_started_at: '',
    pace_games_per_day: 0,
    ...over,
  }
}

export function makePaceVsHltb(over: Partial<PaceVsHLTB> = {}): PaceVsHLTB {
  return {
    calibration_count: 10,
    ratio_vs_rush: 1.05,
    ratio_vs_leisure: 0.4,
    interpolation_t: 0.05,
    player_style: 'rush_to_leisure',
    ...over,
  }
}

export function makeDataset(
  games: WebGame[] = [makeGame()],
  over: Partial<WebDataset> = {},
): WebDataset {
  return {
    games,
    state: makeState(),
    defaults: {
      min_comp_100_polls: 3,
      min_count_comp: 15,
      min_confidence_sum: 18,
      min_playable_tier: 'gold',
      hours_per_day_presets: [2, 4, 6, 8],
    },
    default_summary: {
      qualifying: games.length,
      rush_total: 0,
      leisure_total: 0,
      worst_total: 0,
    },
    pace_vs_hltb: null,
    generated_at: '2026-05-29T00:00:00+00:00',
    ...over,
  }
}

export function makeBudgetToday(over: Partial<BudgetToday> = {}): BudgetToday {
  return {
    gaming_day: '2026-08-28',
    day_starts_at: '06:00 local',
    seconds_used: 3600,
    budget_seconds: 28800,
    seconds_remaining: 25200,
    fraction_used: 0.125,
    blocked: false,
    blocked_at: 0,
    next_warning_seconds: 3600,
    warned_seconds: [],
    ...over,
  }
}

export function makeBudgetSession(over: Partial<BudgetSession> = {}): BudgetSession {
  return {
    available: true,
    observed_at: new Date().toISOString(),
    state: 'engaged',
    reason: 'engaged',
    causes: [],
    idle_seconds: 2,
    screen_held: false,
    game_name: 'Hollow Knight',
    qualifying_count: 3,
    processes: [{ pid: 42, name: 'hollow_knight' }],
    ...over,
  }
}

export function makeBudgetRules(over: Partial<BudgetRules> = {}): BudgetRules {
  return {
    budget_seconds: 28800,
    enforcement: true,
    counts_launchers: true,
    engagement_gate: true,
    idle_grace_seconds: 300,
    require_game_focus: true,
    warn_at: [3600, 1800, 600, 300],
    demo: false,
    masked_launchers: [],
    ...over,
  }
}

export function makeBudget(over: Partial<BudgetSnapshot> = {}): BudgetSnapshot {
  return {
    ok: true,
    readable: true,
    state_status: 'ok',
    error: null,
    today: makeBudgetToday(),
    session: makeBudgetSession(),
    history: [{ day: '2026-08-28', seconds: 3600 }],
    rules: makeBudgetRules(),
    ...over,
  }
}
