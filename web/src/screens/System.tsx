import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { q } from '../api/queries'
import { Card, Facts, PageHead } from '../ui/Page'
import { BackupsCard } from './system/BackupsCard'
import { DaemonCard } from './system/DaemonCard'
import { ServerCard } from './system/ServerCard'

function SetupCard() {
  const { data } = useQuery(q.setup)
  return (
    <Card title="Setup" aside={<Link to="/setup" className="btn btn-ghost btn-small">Open setup</Link>}>
      <Facts
        rows={[
          ['Configured', data ? (data.configured ? 'Yes' : 'No') : '…'],
          ['Steam API key', data ? (data.has_api_key ? 'Stored (never shown)' : 'Missing') : '…'],
          ['Steam ID', <span className="mono">{data?.steam_id ?? '—'}</span>],
        ]}
      />
    </Card>
  )
}

export function System() {
  return (
    <>
      <PageHead title="System" sub="The root daemon, this web server, state backups and setup. There is no way to stop the enforcer." />
      <div className="grid-2">
        <ServerCard />
        <SetupCard />
      </div>
      <DaemonCard />
      <BackupsCard />
    </>
  )
}
