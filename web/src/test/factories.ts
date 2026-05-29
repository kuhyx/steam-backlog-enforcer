// Shared test factories. Lives under src/test/ which is excluded from the
// app build and from coverage.

import type { Filters, WebDataset, WebGame, WebStateInfo } from '../types'

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
    generated_at: '2026-05-29T00:00:00+00:00',
    ...over,
  }
}
