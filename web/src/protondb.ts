// ProtonDB tier logic. `isPlayable` is a faithful port of
// ProtonDBRating.is_playable in steam_backlog_enforcer/protondb.py, so the
// UI's default ProtonDB filter reproduces the CLI's qualifying set exactly.

export const TIER_ORDER: Record<string, number> = {
  native: 0,
  platinum: 1,
  gold: 2,
  silver: 3,
  bronze: 4,
  borked: 5,
  pending: 6,
}

// Tiers offered in the "minimum tier" dropdown, best → worst.
export const SELECTABLE_TIERS = [
  'native',
  'platinum',
  'gold',
  'silver',
  'bronze',
] as const

const MIN_PLAYABLE_TIER = 'gold'
const UNKNOWN_RANK = 99

function rank(tier: string): number {
  return TIER_ORDER[tier] ?? UNKNOWN_RANK
}

/**
 * Faithful port of the CLI's compound playability rule.
 *
 * A game with no rating (or "pending") is not blocked. With a single rating,
 * it must be gold-or-better. With both `tier` and `trending`, neither may be
 * below silver and at least one must be gold-or-better.
 */
export function isPlayable(tier: string, trending: string): boolean {
  if (!tier || tier === 'pending') return true
  const tierRank = rank(tier)
  const minRank = TIER_ORDER[MIN_PLAYABLE_TIER]
  const silverRank = TIER_ORDER.silver
  if (!trending) return tierRank <= minRank
  const trendRank = rank(trending)
  if (tierRank > silverRank || trendRank > silverRank) return false
  return !(tierRank > minRank && trendRank > minRank)
}

/**
 * Simple "minimum acceptable tier" rule for the manual ProtonDB mode.
 *
 * Uses the better (lower-rank) of the two available ratings. Games with no
 * rating fall back to `treatMissingAsPass`.
 */
export function passesMinTier(
  tier: string,
  trending: string,
  minTier: string,
  treatMissingAsPass: boolean,
): boolean {
  const present = [tier, trending].filter((t) => t && t !== 'pending')
  if (present.length === 0) return treatMissingAsPass
  const bestRank = Math.min(...present.map(rank))
  return bestRank <= rank(minTier)
}

/** A short, human-readable label for a game's ProtonDB rating. */
export function tierLabel(tier: string, trending: string): string {
  if (!tier) return '—'
  if (trending && trending !== tier) return `${tier} / ${trending}`
  return tier
}
