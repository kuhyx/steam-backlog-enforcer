import type { JobState } from '../api/jobContract'

const STATE_LABEL: Record<JobState, string> = {
  queued: 'Queued',
  running: 'Running',
  waiting_input: 'Needs your input',
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const STATE_TONE: Record<JobState, string> = {
  queued: 'neutral',
  running: 'accent',
  waiting_input: 'warning',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'neutral',
}

export function StateBadge({ state }: { state: JobState }) {
  return <span className={`pill pill-${STATE_TONE[state]}`}>{STATE_LABEL[state]}</span>
}

interface BarProps {
  /** 0..1, or null for an indeterminate phase. */
  fraction: number | null
  label: string
  tone?: 'accent' | 'success' | 'danger' | 'warning'
  small?: boolean
}

/**
 * Determinate bar with a real `progressbar` role, or an indeterminate sweep
 * when the job reported `total: null`. Width transitions use the motion
 * tokens, so reduced-motion users get instant jumps.
 */
export function ProgressBar({ fraction, label, tone = 'accent', small = false }: BarProps) {
  const pct = fraction === null ? null : Math.round(Math.min(1, Math.max(0, fraction)) * 100)
  return (
    <div
      className={`bar bar-${tone}${small ? ' bar-small' : ''}${pct === null ? ' bar-indeterminate' : ''}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
      aria-valuetext={pct === null ? `${label}: working` : `${label}: ${pct}%`}
    >
      <div className="bar-fill" style={pct === null ? undefined : { width: `${pct}%` }} />
    </div>
  )
}
