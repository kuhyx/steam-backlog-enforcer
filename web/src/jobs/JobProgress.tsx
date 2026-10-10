import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { api } from '../api/client'
import type { JobProgress as Progress, JobState } from '../api/jobContract'
import { q } from '../api/queries'
import { commandLabel, findCommand } from '../commands/catalog'
import { clock, duration } from '../ui/format'
import { ErrorNotice, Notice } from '../ui/Notice'
import { useNow } from '../ui/useNow'
import type { LiveJob } from './hub'
import { ProgressBar, StateBadge } from './ProgressBar'
import { PromptForm } from './PromptForm'
import { useLiveJob } from './useLiveJob'

/** Remaining seconds: the job's own estimate, else extrapolated from pace. */
function eta(p: Progress, live: LiveJob, now: number): number | null {
  if (p.eta_seconds !== undefined && p.eta_seconds !== null) return p.eta_seconds
  if (p.total === null || p.step <= 0 || live.startedProgressAt === null) return null
  const perStep = (now / 1000 - live.startedProgressAt) / p.step
  return perStep * (p.total - p.step)
}

const DONE: ReadonlySet<JobState> = new Set(['succeeded', 'failed', 'cancelled'])
const FINISHED_LABEL: Partial<Record<JobState, string>> = { succeeded: 'Completed', failed: 'Failed', cancelled: 'Cancelled' }

export function JobProgress({ jobId, compact = false }: { jobId: string; compact?: boolean }) {
  const live = useLiveJob(jobId)
  const { data: job } = useQuery(q.job(jobId))
  const { data: commands } = useQuery(q.commands)
  const now = useNow(1000)
  const logRef = useRef<HTMLOListElement>(null)
  const cancel = useMutation({ mutationFn: () => api.cancelJob(jobId) })

  const logCount = live?.logs.length ?? 0
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logCount])

  if (!live) return null
  const state: JobState = live.state ?? job?.state ?? 'queued'
  const progress = live.progress ?? job?.progress ?? null
  const finished = DONE.has(state)
  const spec = job ? findCommand(commands, job.command) : undefined
  const fraction = finished
    ? 1
    : progress && progress.total !== null && progress.total > 0
      ? progress.step / progress.total
      : null
  const tone = state === 'failed' ? 'danger' : state === 'succeeded' ? 'success' : state === 'waiting_input' ? 'warning' : 'accent'
  const waiting = state === 'waiting_input'
  const remaining = progress && !finished && !waiting ? eta(progress, live, now) : null
  const hasErrors = live.logs.some((l) => l.level === 'error')

  return (
    <section className={compact ? 'job job-compact' : 'job'} aria-label={`Job ${job ? commandLabel(job.command) : jobId}`}>
      <div className="job-head">
        <h3 className="job-title">{job ? commandLabel(job.command) : 'Job'}</h3>
        <StateBadge state={state} />
        <span className="job-meta">
          {job && duration(job.started_at, job.ended_at, now)}
          {!finished && (
            <span className={live.connected ? 'dot dot-live' : 'dot dot-off'} title={live.connected ? 'Live' : 'Reconnecting…'}>
              <span className="sr-only">{live.connected ? 'Live' : 'Reconnecting'}</span>
            </span>
          )}
        </span>
      </div>

      <div className="job-phase" aria-live="polite">
        <span className="job-label">{finished ? FINISHED_LABEL[state] : waiting ? 'Waiting for your answer' : (progress?.label ?? 'Starting…')}</span>
        {!finished && progress && progress.total !== null && (
          <span className="job-step">
            Step {progress.step} of {progress.total}
          </span>
        )}
      </div>
      <ProgressBar fraction={fraction} label={progress?.label ?? 'Progress'} tone={tone} />
      {!finished && (
        <div className="job-sub">
          <span className="job-item">{progress?.item ?? ' '}</span>
          <span className="job-eta">{remaining !== null ? `about ${clock(remaining)} left` : waiting ? 'paused' : progress?.total === null ? 'working…' : ''}</span>
        </div>
      )}

      {live.prompt && state === 'waiting_input' && <PromptForm key={live.prompt.prompt_id} jobId={jobId} prompt={live.prompt} />}

      {live.result && (
        <Notice tone={live.result.ok ? 'success' : 'danger'} title={live.result.ok ? 'Done' : 'Did not complete'}>
          {live.result.summary}
        </Notice>
      )}

      {cancel.error && <ErrorNotice error={cancel.error} />}
      {(spec?.cancellable || waiting) && !finished && (
        <div className="actions">
          <button type="button" className="btn btn-ghost" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            {cancel.isPending ? 'Cancelling…' : 'Cancel job'}
          </button>
        </div>
      )}

      <details className="job-log" open={!compact && (hasErrors || finished) ? true : undefined}>
        <summary>Log ({logCount} lines)</summary>
        <ol ref={logRef} className="log" tabIndex={0} aria-label="Job log">
          {live.logs.map((l) => (
            <li key={l.seq} className={`log-${l.level}`}>
              <time dateTime={l.ts}>{l.ts.slice(11, 19)}</time> {l.message}
            </li>
          ))}
          {logCount === 0 && <li className="muted">{finished ? 'No output.' : 'No output yet.'}</li>}
        </ol>
      </details>
    </section>
  )
}
