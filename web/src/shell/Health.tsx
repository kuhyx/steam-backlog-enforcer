import { useQuery } from '@tanstack/react-query'
import { q } from '../api/queries'
import { ErrorNotice } from '../ui/Notice'
import { useServerRestart } from './useServerRestart'

const DAEMON_TONE = { running: 'success', restarting: 'warning', unreachable: 'danger' } as const

export function HealthBadges() {
  const server = useQuery(q.server)
  const daemon = useQuery(q.daemon)
  const serverTone = server.error ? 'danger' : server.data?.stale ? 'warning' : 'success'
  const serverText = server.error ? 'Server down' : server.data?.stale ? 'Server stale' : 'Server ok'
  const d = daemon.data?.state
  return (
    <div className="health" aria-label="Health">
      <span className={`pill pill-${serverTone}`} title={server.data ? `v${server.data.version}` : undefined}>
        {serverText}
      </span>
      <span className={`pill pill-${d ? DAEMON_TONE[d] : 'neutral'}`}>Daemon {d ?? '…'}</span>
    </div>
  )
}

/** Banner shown on every screen while the running server is older than the code on disk. */
export function StaleBanner() {
  const server = useQuery(q.server)
  const { restart, restarting } = useServerRestart()
  if (!server.data?.stale) return null
  return (
    <div className="banner banner-warning" role="status">
      <span>
        <strong>The web server is running stale code.</strong> Restart it to pick up the new version.
      </span>
      <button type="button" className="btn btn-primary btn-small" disabled={restarting || restart.isPending} onClick={() => restart.mutate()}>
        {restarting ? 'Restarting…' : 'Restart server'}
      </button>
      {restart.error && <ErrorNotice error={restart.error} />}
    </div>
  )
}
