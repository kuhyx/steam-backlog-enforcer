import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { Job } from '../api/jobContract'
import { isActive, q } from '../api/queries'
import { commandLabel } from '../commands/catalog'
import { ProgressBar } from '../jobs/ProgressBar'
import { useLiveJob } from '../jobs/useLiveJob'

/** Top-bar chip for each running job, live from its SSE stream. */
function Chip({ job }: { job: Job }) {
  const live = useLiveJob(job.id)
  const state = live?.state ?? job.state
  const p = live?.progress ?? job.progress
  const fraction = p && p.total ? p.step / p.total : null
  const waiting = state === 'waiting_input'
  return (
    <Link
      to="/jobs/$jobId"
      params={{ jobId: job.id }}
      className={waiting ? 'jobchip jobchip-wait' : 'jobchip'}
      aria-label={`${commandLabel(job.command)}: ${waiting ? 'needs your input' : (p?.label ?? 'running')}`}
    >
      <span className="jobchip-label">
        {commandLabel(job.command)}
        <span className="jobchip-sub">{waiting ? 'needs input' : p?.total ? `${p.step}/${p.total}` : '…'}</span>
      </span>
      <ProgressBar fraction={fraction} label={commandLabel(job.command)} tone={waiting ? 'warning' : 'accent'} small />
    </Link>
  )
}

export function JobIndicator() {
  const { data } = useQuery(q.jobs)
  const active = (data ?? []).filter(isActive).slice(0, 2)
  if (active.length === 0) return null
  return (
    <div className="jobchips" aria-live="polite" aria-label="Running jobs">
      {active.map((j) => (
        <Chip key={j.id} job={j} />
      ))}
    </div>
  )
}
