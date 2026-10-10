import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { q } from '../../api/queries'
import { useRunner } from '../../commands/runnerContext'
import { ago, clock } from '../../ui/format'
import { CommandLine, ErrorNotice, Loading, Notice } from '../../ui/Notice'
import { Card, Facts } from '../../ui/Page'
import { useNow } from '../../ui/useNow'

/**
 * The root daemon: state, live journal tail, rate-limited restart and the
 * 60 s demo run. Deliberately no stop/disable — the contract has none.
 */
export function DaemonCard() {
  const { data, error } = useQuery(q.daemon)
  const { run } = useRunner()
  const now = useNow(1000)
  const logRef = useRef<HTMLPreElement>(null)
  const lines = data?.journal_tail.length ?? 0
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  if (error) return <Card title="Enforcer daemon"><ErrorNotice error={error} /></Card>
  if (!data) return <Card title="Enforcer daemon"><Loading what="daemon status" /></Card>

  const waitMs = data.restart_available_at ? Date.parse(data.restart_available_at) - now : 0
  const limited = waitMs > 0
  return (
    <Card title="Enforcer daemon">
      {data.state === 'unreachable' && (
        <Notice tone="danger" title="Daemon unreachable">
          Privileged actions (store unblock, gaming reset/block/unblock, restart) are unavailable. Check it from a terminal:
          <CommandLine command="systemctl status steam-backlog-enforcer" />
        </Notice>
      )}
      <Facts
        rows={[
          ['State', data.state],
          ['PID', data.pid ?? '—'],
          ['Up since', data.started_at ? ago(data.started_at, now) : '—'],
        ]}
      />
      <div className="actions">
        <button
          type="button"
          className="btn btn-ghost"
          aria-disabled={limited || data.state !== 'running'}
          onClick={() => {
            if (!limited && data.state === 'running') run('enforce', { demo: 0 })
          }}
        >
          {limited ? `Restart available in ${clock(waitMs / 1000)}` : 'Restart daemon…'}
        </button>
        {/* enforce is a "screen" command, so CommandButton would render a link
            back to this page; open the runner directly, as restart does. */}
        <button type="button" className="btn btn-ghost" onClick={() => run('enforce', { demo: 1 })}>
          Demo run (enforce --demo)…
        </button>
      </div>
      <h3 className="h3">Journal</h3>
      <pre ref={logRef} className="journal" tabIndex={0} aria-label="Daemon journal (live)">
        {data.journal_tail.length ? data.journal_tail.join('\n') : 'No journal lines.'}
      </pre>
    </Card>
  )
}
