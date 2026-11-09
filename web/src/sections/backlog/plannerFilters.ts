// The planner's estimate filters (was PlannerView's defaultFilters) and their
// URL-hash form. Only values that differ from the CLI defaults are written,
// so a fresh page has an empty hash and "Reset to CLI defaults" clears it.

import { SELECTABLE_TIERS } from '../../protondb'
import type { EstimateBasis, Filters, PlaytimeMode, ProtonMode, WebDefaults } from '../../types'

export function defaultFilters(d: WebDefaults): Filters {
  return {
    minCountComp: d.min_count_comp,
    minComp100: d.min_comp_100_polls,
    minConfidenceSum: d.min_confidence_sum,
    protonMode: 'playable',
    protonMinTier: d.min_playable_tier,
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
  }
}

type NumberKey = 'dailyHours' | 'minCountComp' | 'minComp100' | 'minConfidenceSum' | 'maxHoursPerGame' | 'fallbackHours'
type FlagKey = 'protonTreatMissingAsPass' | 'includeNoData'

const NUMBERS: readonly (readonly [string, NumberKey])[] = [
  ['daily', 'dailyHours'],
  ['mincomp', 'minCountComp'],
  ['min100', 'minComp100'],
  ['minconf', 'minConfidenceSum'],
  ['maxh', 'maxHoursPerGame'],
  ['fallback', 'fallbackHours'],
]
const FLAGS: readonly (readonly [string, FlagKey])[] = [
  ['keepmissing', 'protonTreatMissingAsPass'],
  ['nodata', 'includeNoData'],
]
const BASES: readonly EstimateBasis[] = ['rush', 'leisure', 'worst', 'pace']
const PROTON: readonly ProtonMode[] = ['playable', 'minTier']
const PLAYTIME: readonly PlaytimeMode[] = ['all', 'started', 'untouched']
const TIERS: readonly string[] = SELECTABLE_TIERS

const pickOne = <T extends string>(allowed: readonly T[], raw: string | null, fallback: T): T =>
  allowed.find((v) => v === raw) ?? fallback

/** Write the non-default planner filters into `p`. */
export function writeFilters(f: Filters, d: Filters, p: URLSearchParams): void {
  for (const [key, field] of NUMBERS) if (f[field] !== d[field]) p.set(key, String(f[field]))
  for (const [key, field] of FLAGS) if (f[field] !== d[field]) p.set(key, f[field] ? '1' : '0')
  if (f.basis !== d.basis) p.set('basis', f.basis)
  if (f.protonMode !== d.protonMode) p.set('proton', f.protonMode)
  if (f.protonMinTier !== d.protonMinTier) p.set('tier', f.protonMinTier)
  if (f.playtimeMode !== d.playtimeMode) p.set('playtime', f.playtimeMode)
  if (f.targetDate) p.set('target', f.targetDate)
  if (f.search) p.set('q', f.search)
  if (f.excluded.size > 0) p.set('x', [...f.excluded].sort((a, b) => a - b).join(','))
}

/** The planner filters `p` describes, anything absent or invalid from `d`. */
export function readFilters(p: URLSearchParams, d: Filters): Filters {
  const f: Filters = { ...d, excluded: new Set<number>() }
  for (const [key, field] of NUMBERS) {
    const raw = p.get(key)
    const n = raw ? Number(raw) : Number.NaN
    if (Number.isFinite(n)) f[field] = n
  }
  for (const [key, field] of FLAGS) {
    const raw = p.get(key)
    if (raw === '1' || raw === '0') f[field] = raw === '1'
  }
  f.basis = pickOne(BASES, p.get('basis'), d.basis)
  f.protonMode = pickOne(PROTON, p.get('proton'), d.protonMode)
  f.protonMinTier = pickOne(TIERS, p.get('tier'), d.protonMinTier)
  f.playtimeMode = pickOne(PLAYTIME, p.get('playtime'), d.playtimeMode)
  const target = p.get('target') ?? ''
  f.targetDate = /^\d{4}-\d{2}-\d{2}$/.test(target) ? target : ''
  f.search = p.get('q') ?? ''
  const ids = (p.get('x') ?? '').split(',').map(Number)
  f.excluded = new Set(ids.filter((n) => Number.isInteger(n) && n > 0))
  return f
}
