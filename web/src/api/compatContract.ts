// The Proton map's shapes (`GET /api/compat`). Split from contract.ts (file-length
// cap); same frozen contract, same prose spec: DOCS-web-install.md.

/**
 * One installed game's compat-tool decision (`GET /api/compat`), from the
 * installer's own `--map-installed` rows (steam_installer/compat_rows.py).
 */
export interface CompatRow {
  app_id: number
  name: string
  /** The tool config.vdf maps it to; null = unmapped (Valve's default). */
  current: string | null
  priority: string | null
  /** The tool after apply; null = Valve's default. */
  decided: string | null
  /** Why the decision keeps Valve's default; empty = map it. */
  reasons: string[]
  /** Why apply leaves a mappable game alone ("already mapped", "kept: …"). */
  note: string | null
  map: boolean
  /** Whether `map-installed` would rewrite this game's entry. */
  changes: boolean
  /** False when Steam's app cache does not know the game. */
  cached: boolean
}

export interface CompatPayload {
  tool: string
  tool_ready: boolean
  rows: CompatRow[]
}
