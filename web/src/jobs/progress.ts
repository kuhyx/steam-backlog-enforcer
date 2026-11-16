// Job state pill and progress bar (was jobs/ProgressBar.tsx).

import type { JobState } from '../api/jobContract'
import type { IconId } from '../icons/registry'
import { iconMark, iconWord } from '../icons/render'
import { h } from '../lib/dom'

const STATE_ICON = {
  queued: 'job.state.queued',
  running: 'job.state.running',
  waiting_input: 'job.state.waiting_input',
  succeeded: 'job.state.succeeded',
  failed: 'job.state.failed',
  cancelled: 'job.state.cancelled',
} as const satisfies Record<JobState, IconId>

const STATE_TONE: Record<JobState, string> = {
  queued: 'neutral',
  running: 'accent',
  waiting_input: 'warning',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'neutral',
}

export function stateBadge(state: JobState): HTMLSpanElement {
  const id = STATE_ICON[state]
  return h('span', { class: `pill pill-${STATE_TONE[state]}`, 'aria-label': state }, iconMark(id, 'pill-icon'), iconWord(id))
}

export type BarTone = 'accent' | 'success' | 'danger' | 'warning'

/**
 * Determinate bar with a real `progressbar` role, or an indeterminate sweep
 * when the job reported `total: null` (`fraction` null). Width transitions
 * use the motion tokens, so reduced-motion users get instant jumps.
 */
export function progressBar(fraction: number | null, label: string, tone: BarTone = 'accent', small = false): HTMLDivElement {
  const pct = fraction === null ? null : Math.round(Math.min(1, Math.max(0, fraction)) * 100)
  const fill = h('div', { class: 'bar-fill' })
  if (pct !== null) fill.style.width = `${pct}%`
  return h(
    'div',
    {
      class: `bar bar-${tone}${small ? ' bar-small' : ''}${pct === null ? ' bar-indeterminate' : ''}`,
      role: 'progressbar',
      'aria-label': label,
      'aria-valuemin': 0,
      'aria-valuemax': 100,
      'aria-valuenow': pct,
      'aria-valuetext': pct === null ? `${label}: working` : `${label}: ${pct}%`,
    },
    fill,
  )
}
