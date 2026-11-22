// Server health and state-backup shapes. Split from contract.ts (file-length
// cap); same frozen contract, same prose spec: DOCS-web-control-api.md.

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
