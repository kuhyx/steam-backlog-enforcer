import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { StatusPayload } from '../api/contract'
import { q } from '../api/queries'
import { CommandButton } from '../commands/CommandCard'
import { commandLabel } from '../commands/catalog'
import { fmtDuration } from '../format'
import { ProgressBar, StateBadge } from '../jobs/ProgressBar'
import { ago } from '../ui/format'
import { Empty, ErrorNotice, Loading } from '../ui/Notice'
import { Card, Facts, PageHead } from '../ui/Page'

function StatusCard({ s }: { s: StatusPayload }) {
  return (
    <Card title="Assignment" aside={<CommandButton name="check" label="Check now" />}>
      <p className="hero-game">{s.current_game_name ?? 'Nothing assigned'}</p>
      <Facts
        rows={[
          ['Installed', s.assigned_game_installed ? 'Yes' : <span className="text-warning">No — install it from Library</span>],
          ['Games finished', s.finished_count],
          ['Store', s.store_blocked ? 'Blocked' : <span className="text-warning">Unblocked</span>],
          ['Installed games', s.installed_count],
          [
            'Total block',
            s.total_block.active ? <span className="text-danger">{s.total_block.days_remaining} days left</span> : 'Off',
          ],
          [
            'Manual picks',
            s.manual_picks.length ? s.manual_picks.map((p) => `${p.name} (${p.age_days} d)`).join(', ') : 'None',
          ],
        ]}
      />
    </Card>
  )
}

function BudgetGlance() {
  const { data, error } = useQuery(q.budget)
  if (error) return <Card title="Gaming today"><ErrorNotice error={error} /></Card>
  if (!data) return <Card title="Gaming today"><Loading what="budget" /></Card>
  const t = data.today
  return (
    <Card title="Gaming today" aside={<Link to="/gaming" className="btn btn-ghost btn-small">Details</Link>}>
      {t ? (
        <>
          <p className="hero-num">
            {fmtDuration(t.seconds_remaining)} <span className="muted">left of {fmtDuration(t.budget_seconds)}</span>
          </p>
          <ProgressBar fraction={t.fraction_used} label="Budget used" tone={t.blocked ? 'danger' : t.fraction_used > 0.8 ? 'warning' : 'accent'} />
          <p className="field-help">
            {t.blocked ? 'Blocked for today.' : `Now: ${data.session.billing_label || 'nothing billing'}`}
          </p>
        </>
      ) : (
        <p className="text-danger">{data.error ?? 'Budget state unavailable.'}</p>
      )}
    </Card>
  )
}

function RecentJobs() {
  const { data, error } = useQuery(q.jobs)
  return (
    <Card title="Recent jobs" aside={<Link to="/jobs" className="btn btn-ghost btn-small">All jobs</Link>}>
      {error && <ErrorNotice error={error} />}
      {data?.length === 0 && <Empty>No jobs yet. Run one from the actions or press Ctrl K.</Empty>}
      <ul className="rows">
        {data?.slice(0, 5).map((j) => (
          <li key={j.id}>
            <Link to="/jobs/$jobId" params={{ jobId: j.id }} className="row-link">
              <span>{commandLabel(j.command)}</span>
              <span className="muted grow ellipsis">{j.summary ?? j.progress?.label ?? ''}</span>
              <span className="muted">{ago(j.created_at)}</span>
              <StateBadge state={j.state} />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function Dashboard() {
  const { data, error } = useQuery(q.status)
  return (
    <>
      <PageHead title="Dashboard" sub="What the enforcer is doing right now.">
        <CommandButton name="done" label="I got an achievement" tone="primary" />
        <CommandButton name="install" label="Install assigned" />
        <CommandButton name="pick" label="Pick next" />
        <CommandButton name="scan" label="Scan" />
      </PageHead>
      <div className="grid-2">
        {error ? <Card title="Assignment"><ErrorNotice error={error} /></Card> : data ? <StatusCard s={data} /> : <Card title="Assignment"><Loading what="status" /></Card>}
        <BudgetGlance />
      </div>
      <RecentJobs />
    </>
  )
}
