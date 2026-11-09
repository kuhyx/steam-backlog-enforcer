// Build-time stamp for `<meta name="sbe-build">` (rendered in Shell.astro's
// frontmatter, never shipped to the browser). The commit says which code is
// served (`curl … | grep $(git rev-parse --short HEAD)`); the time part makes
// every rebuild distinct, so an open tab reloads onto an uncommitted rebuild
// too. Computed once per process: a dev server keeps one stamp, so pages do
// not reload themselves every poll.

import { execSync } from 'node:child_process'

export function commitId(run: (cmd: string) => string = (cmd) => execSync(cmd, { encoding: 'utf8' })): string {
  try {
    return run('git rev-parse --short HEAD').trim()
  } catch {
    return 'unknown'
  }
}

export const BUILD_STAMP = `${commitId()}.${Date.now().toString(36)}`
