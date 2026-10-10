// Real-looking backlog for the dev-only mock API. Hours are derived from a
// stable hash so every reload shows the same numbers.

import type { InstalledGame } from '../src/api/contract.ts'
import type { WebGame } from '../src/types.ts'

export const GAMES: ReadonlyArray<readonly [number, string]> = [
  [1145360, 'Hades'],
  [367520, 'Hollow Knight'],
  [504230, 'Celeste'],
  [588650, 'Dead Cells'],
  [413150, 'Stardew Valley'],
  [646570, 'Slay the Spire'],
  [590380, 'Into the Breach'],
  [632470, 'Disco Elysium'],
  [753640, 'Outer Wilds'],
  [653530, 'Return of the Obra Dinn'],
  [1092790, 'Inscryption'],
  [268910, 'Cuphead'],
  [1057090, 'Ori and the Will of the Wisps'],
  [264710, 'Subnautica'],
  [620, 'Portal 2'],
  [220, 'Half-Life 2'],
  [460950, 'Katana ZERO'],
  [219150, 'Hotline Miami'],
  [391540, 'Undertale'],
  [736260, 'Baba Is You'],
  [553420, 'TUNIC'],
  [972660, 'Spiritfarer'],
  [1055540, 'A Short Hike'],
  [383870, 'Firewatch'],
  [501300, 'What Remains of Edith Finch'],
  [683320, 'GRIS'],
  [304430, 'INSIDE'],
  [262060, 'Darkest Dungeon'],
  [212680, 'FTL: Faster Than Light'],
  [1794680, 'Vampire Survivors'],
  [2379780, 'Balatro'],
  [1313140, 'Cult of the Lamb'],
  [894020, "Death's Door"],
  [1205520, 'Pentiment'],
  [1578650, 'Citizen Sleeper'],
  [1262350, 'SIGNALIS'],
  [1451940, 'NEEDY GIRL OVERDOSE'],
  [1533420, 'Neon White'],
  [2231450, 'Pizza Tower'],
  [1868140, 'DAVE THE DIVER'],
  [1244090, 'Sea of Stars'],
  [1229240, 'Chained Echoes'],
]

const TIERS = ['platinum', 'gold', 'gold', 'silver', 'platinum', 'bronze', 'borked', 'pending']

/** Small deterministic hash so fixture numbers are stable across reloads. */
export function hash(n: number): number {
  let x = n ^ 0x5bd1e995
  x = Math.imul(x ^ (x >>> 15), 0x2c1b3c6d)
  x = Math.imul(x ^ (x >>> 12), 0x297a2d39)
  return (x ^ (x >>> 15)) >>> 0
}

export function nameOf(appId: number): string | null {
  return GAMES.find(([id]) => id === appId)?.[1] ?? null
}

export function makeWebGame(appId: number, name: string): WebGame {
  const h = hash(appId)
  const rush = 4 + (h % 60)
  const noData = h % 13 === 0
  return {
    app_id: appId,
    name,
    completion_pct: h % 7 === 0 ? (h % 80) + 5 : 0,
    playtime_minutes: h % 3 === 0 ? (h % 900) : 0,
    rush_hours: noData ? -1 : rush,
    leisure_hours: noData ? -1 : Math.round(rush * 1.8),
    worst_hours: noData ? -1 : Math.round(rush * 2.4),
    count_comp: noData ? 0 : 5 + (h % 70),
    comp_100_count: noData ? 0 : 1 + (h % 12),
    hltb_game_id: noData ? 0 : 10000 + (h % 90000),
    protondb_tier: TIERS[h % TIERS.length],
    protondb_trending_tier: TIERS[(h >>> 3) % TIERS.length],
    protondb_score: (h % 100) / 100,
  }
}

export function makeInstalled(assignedId: number): InstalledGame[] {
  const ids = [assignedId, 367520, 620, 413150, 1794680, 2379780]
  return ids.map((id) => ({
    app_id: id,
    name: nameOf(id) ?? `App ${id}`,
    size_bytes: (hash(id) % 40_000 + 300) * 1024 * 1024,
    assigned: id === assignedId,
    protected: id === 620,
  }))
}
