// Painted marks for what a job's `result.data` says (textgate: icons, the
// summary stays spoken). Only `install` sends these flags today
// (`InstallResultData` in the contract); any other data paints nothing.

import type { InstallResultData } from '../api/contract'
import type { IconId } from '../icons/registry'

/** Runtime check at the event-stream boundary: `data` is `unknown` there. */
function isInstallResultData(data: unknown): data is InstallResultData {
  if (typeof data !== 'object' || data === null) return false
  const d = data as Record<string, unknown>
  return typeof d.dry_run === 'boolean' && (d.fast_install_skipped === null || d.fast_install_skipped === 'game_running')
}

export function resultMarks(data: unknown): IconId[] {
  if (!isInstallResultData(data)) return []
  const marks: IconId[] = []
  if (data.dry_run) marks.push('result.dry-run')
  if (data.fast_install_skipped === 'game_running') marks.push('result.game-running')
  return marks
}
