// Every game the UI knows a name for (backlog snapshot, installed list,
// current assignment, manual picks), for app_id pickers and for filling
// `{game_name}` / `{count}` in phrase previews (was useGameLookup.ts).

import type { InstalledPayload, StatusPayload, WebDataset } from '../api/contract'
import type { PhraseContext } from './catalog'
import type { GameOption } from './params'

export function gameLookup(
  dataset: WebDataset | undefined,
  installed: InstalledPayload | undefined,
  status: StatusPayload | undefined,
): { games: GameOption[]; ctx: PhraseContext } {
  const byId = new Map<number, string>()
  for (const g of dataset?.games ?? []) byId.set(g.app_id, g.name)
  for (const g of installed?.games ?? []) byId.set(g.app_id, g.name)
  for (const p of status?.manual_picks ?? []) byId.set(p.app_id, p.name)
  if (status?.current_app_id && status.current_game_name) byId.set(status.current_app_id, status.current_game_name)
  const games = [...byId].map(([app_id, name]) => ({ app_id, name })).sort((a, b) => a.name.localeCompare(b.name))
  return { games, ctx: { gameName: (id) => byId.get(id) ?? null, installed: installed?.games ?? null } }
}
