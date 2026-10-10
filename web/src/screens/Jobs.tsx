import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { q } from '../api/queries'
import { commandLabel } from '../commands/catalog'
import { JobProgress } from '../jobs/JobProgress'
import { StateBadge } from '../jobs/ProgressBar'
import { dateTime, duration } from '../ui/format'
import { Empty, ErrorNotice, Loading } from '../ui/Notice'
import { Card, PageHead } from '../ui/Page'
import { useNow } from '../ui/useNow'

export function Jobs() {
  const { data, error } = useQuery(q.jobs)
  const now = useNow(1000)
  return (
    <>
      <PageHead title="Jobs" sub="The last 50 jobs. They keep running if you close the page." />
      <Card>
        {error && <ErrorNotice error={error} />}
        {!data && !error && <Loading what="jobs" />}
        {data?.length === 0 && <Empty>No jobs yet. Press Ctrl K to run a command.</Empty>}
        {data && data.length > 0 && (
          <div className="tbl" tabIndex={0} role="region" aria-label="Job history">
            <table>
              <thead>
                <tr>
                  <th scope="col">Command</th>
                  <th scope="col">State</th>
                  <th scope="col">Started</th>
                  <th scope="col" className="num">Took</th>
                  <th scope="col">Summary</th>
                </tr>
              </thead>
              <tbody>
                {data.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to="/jobs/$jobId" params={{ jobId: j.id }}>{commandLabel(j.command)}</Link>
                      {Object.keys(j.params).length > 0 && (
                        <span className="muted mono"> {Object.entries(j.params).map(([k, v]) => `${k}=${v}`).join(' ')}</span>
                      )}
                    </td>
                    <td><StateBadge state={j.state} /></td>
                    <td className="muted">{dateTime(j.created_at)}</td>
                    <td className="num mono">{duration(j.started_at, j.ended_at, now)}</td>
                    <td className="ellipsis">{j.summary ?? j.progress?.label ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

export function JobDetail({ jobId }: { jobId: string }) {
  const { data, error } = useQuery(q.job(jobId))
  return (
    <>
      <PageHead title={data ? commandLabel(data.command) : 'Job'} sub={<>Job <span className="mono">{jobId}</span>{data && <> · created {dateTime(data.created_at)}</>}</>}>
        <Link to="/jobs" className="btn btn-ghost">All jobs</Link>
      </PageHead>
      {error && <ErrorNotice error={error} />}
      <Card>
        <JobProgress jobId={jobId} />
      </Card>
    </>
  )
}
