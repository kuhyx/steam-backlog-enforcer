import { useQuery } from '@tanstack/react-query'
import { q } from '../../api/queries'
import { useServerRestart } from '../../shell/useServerRestart'
import { ago, dateTime } from '../../ui/format'
import { ErrorNotice, Loading, Notice } from '../../ui/Notice'
import { Card, Facts } from '../../ui/Page'

/** `serve`: the unprivileged web server's health and restart. */
export function ServerCard() {
  const { data, error } = useQuery(q.server)
  const { restart, restarting } = useServerRestart()
  return (
    <Card title="Web server">
      {error && <ErrorNotice error={error} />}
      {!data && !error && <Loading what="server health" />}
      {data && (
        <>
          {data.stale && <Notice tone="warning" title="Stale">The code on disk is newer than this process.</Notice>}
          <Facts
            rows={[
              ['Version', <span className="mono">{data.version}</span>],
              ['Started', `${dateTime(data.started_at)} (${ago(data.started_at)})`],
              ['Code', data.stale ? 'stale' : 'current'],
            ]}
          />
        </>
      )}
      {restart.error && <ErrorNotice error={restart.error} />}
      <div className="actions">
        <button type="button" className="btn btn-ghost" disabled={restarting || restart.isPending} onClick={() => restart.mutate()}>
          {restarting ? 'Restarting… the page reloads when it is back' : 'Restart server'}
        </button>
      </div>
    </Card>
  )
}
