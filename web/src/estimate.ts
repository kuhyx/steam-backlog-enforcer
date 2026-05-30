// Pure filtering + completion-time estimation. Mirrors the logic in
// steam_backlog_enforcer/_stats.py and _web_dataset.py so that, at the CLI
// default thresholds, the totals reproduce the `stats` command exactly.

import { isPlayable, passesMinTier } from './protondb'
import type { EstimateBasis, Filters, PaceVsHLTB, WebDataset, WebGame } from './types'

export interface GameRow {
  game: WebGame
  // Effective hours per model (fallback applied for no-data games when the
  // "include no-data" toggle is on; otherwise -1 when missing).
  rush: number
  leisure: number
  worst: number
  // Hours under the selected basis — used for the cap, table, and chart.
  lengthHours: number
  noData: boolean
  passesFilters: boolean // all threshold/extra filters (not manual exclusion)
  excluded: boolean // manually excluded by the user
  included: boolean // counted in totals
}

export interface EstimateResult {
  rows: GameRow[]
  included: GameRow[]
  rushTotal: number
  leisureTotal: number
  worstTotal: number
  remainingGames: number
}

/** True when HLTB has no length of any kind for this game. */
function isNoData(g: WebGame): boolean {
  return g.rush_hours <= 0 && g.leisure_hours <= 0 && g.worst_hours <= 0
}

/** Raw per-game hours for the selected basis (pace uses leisure as a proxy). */
function rawBasisHours(g: WebGame, basis: EstimateBasis): number {
  switch (basis) {
    case 'rush':
      return g.rush_hours
    case 'worst':
      return g.worst_hours
    case 'leisure':
    case 'pace':
      return g.leisure_hours
  }
}

/** Apply the no-data fallback: keep positive values, substitute fallback when
 * the whole game is missing and the user opted to include such games. */
function effective(raw: number, noData: boolean, f: Filters): number {
  if (raw > 0) return raw
  if (noData && f.includeNoData) return f.fallbackHours
  return -1
}

function passesConfidence(g: WebGame, f: Filters): boolean {
  return (
    g.comp_100_count >= f.minComp100 &&
    g.count_comp >= f.minCountComp &&
    g.comp_100_count + g.count_comp >= f.minConfidenceSum
  )
}

function passesProton(g: WebGame, f: Filters): boolean {
  if (f.protonMode === 'playable') {
    return isPlayable(g.protondb_tier, g.protondb_trending_tier)
  }
  return passesMinTier(
    g.protondb_tier,
    g.protondb_trending_tier,
    f.protonMinTier,
    f.protonTreatMissingAsPass,
  )
}

function passesPlaytime(g: WebGame, f: Filters): boolean {
  if (f.playtimeMode === 'started') return g.playtime_minutes > 0
  if (f.playtimeMode === 'untouched') return g.playtime_minutes === 0
  return true
}

function buildRow(g: WebGame, f: Filters): GameRow {
  const noData = isNoData(g)
  const rush = effective(g.rush_hours, noData, f)
  const leisure = effective(g.leisure_hours, noData, f)
  const worst = effective(g.worst_hours, noData, f)
  const lengthHours = effective(rawBasisHours(g, f.basis), noData, f)

  // Threshold + extra filters, evaluated independently of manual exclusion.
  let passes = passesConfidence(g, f) && passesProton(g, f) && passesPlaytime(g, f)
  if (passes && !f.includeNoData && noData) passes = false
  if (passes && f.maxHoursPerGame > 0 && lengthHours > f.maxHoursPerGame) {
    passes = false
  }

  const excluded = f.excluded.has(g.app_id)
  return {
    game: g,
    rush,
    leisure,
    worst,
    lengthHours,
    noData,
    passesFilters: passes,
    excluded,
    included: passes && !excluded,
  }
}

/** Run all filters and compute the qualifying totals. */
export function applyFilters(
  dataset: WebDataset,
  filters: Filters,
): EstimateResult {
  const rows = dataset.games.map((g) => buildRow(g, filters))
  const included = rows.filter((r) => r.included)

  let rushTotal = 0
  let leisureTotal = 0
  let worstTotal = 0
  for (const r of included) {
    if (r.rush > 0) rushTotal += r.rush
    if (r.leisure > 0) leisureTotal += r.leisure
    if (r.worst > 0) worstTotal += r.worst
  }

  return {
    rows,
    included,
    rushTotal: Math.round(rushTotal * 10) / 10,
    leisureTotal: Math.round(leisureTotal * 10) / 10,
    worstTotal: Math.round(worstTotal * 10) / 10,
    remainingGames: included.length,
  }
}

/** Days to finish `hours` at `daily` hours/day (floor — matches the CLI). */
export function etaDays(hours: number, daily: number): number | null {
  if (hours <= 0 || daily <= 0) return null
  return Math.floor(hours / daily)
}

/** Days to finish `remaining` games at `pace` games/day (floor). */
export function paceDays(remaining: number, pace: number): number | null {
  if (remaining <= 0 || pace <= 0) return null
  return Math.floor(remaining / pace)
}

/**
 * Estimate the player's personal backlog total from their calibrated pace.
 *
 * Uses interpolation_t when leisure data exists, falls back to ratio_vs_rush
 * otherwise.  Returns null when there is no calibration data.
 */
export function playerEstimatedTotal(
  rushTotal: number,
  leisureTotal: number,
  pace: PaceVsHLTB | null,
): number | null {
  if (!pace || pace.calibration_count === 0) return null
  if (pace.interpolation_t !== -1) {
    return rushTotal + pace.interpolation_t * (leisureTotal - rushTotal)
  }
  if (pace.ratio_vs_rush !== -1) {
    return rushTotal * pace.ratio_vs_rush
  }
  return null
}

/** Total hours for the selected basis, or null for the pace (count) basis. */
export function basisTotal(
  result: EstimateResult,
  basis: EstimateBasis,
): number | null {
  if (basis === 'rush') return result.rushTotal
  if (basis === 'leisure') return result.leisureTotal
  if (basis === 'worst') return result.worstTotal
  return null
}
