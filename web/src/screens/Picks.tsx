import { useQuery } from '@tanstack/react-query'
import { q } from '../api/queries'
import { CommandButton, CommandCard } from '../commands/CommandCard'
import { Empty, ErrorNotice, Loading } from '../ui/Notice'
import { Actions, Card, PageHead } from '../ui/Page'

/** Everything that changes which game is assigned. */
export function Picks() {
  const { data, error } = useQuery(q.status)
  return (
    <>
      <PageHead
        title="Picks"
        sub={data?.current_game_name ? <>Assigned: <strong>{data.current_game_name}</strong></> : 'Which game you are playing, and how to move on.'}
      />
      <Actions>
        <CommandCard name="check" label="Check" />
        <CommandCard name="done" label="Done" tone="primary" />
        <CommandCard name="pick" label="Pick…" />
        <CommandCard name="scan" label="Scan" />
        <CommandCard name="pick-manual" label="Lock in a game…" />
      </Actions>
      <Card title="Manual picks">
        {error && <ErrorNotice error={error} />}
        {!data && !error && <Loading what="status" />}
        {data && data.manual_picks.length === 0 && (
          <Empty>No manual picks. "Lock in a game" adds one and locks most commands for 14 days.</Empty>
        )}
        <ul className="rows">
          {data?.manual_picks.map((p) => (
            <li key={p.app_id} className="row">
              <span className="grow">
                <strong>{p.name}</strong> <span className="muted">· picked {p.age_days} d ago · {p.app_id}</span>
              </span>
              <CommandButton name="abandon-pick" preset={{ app_id: p.app_id }} label="Abandon…" tone="danger" />
            </li>
          ))}
        </ul>
        {data && data.manual_picks.length === 0 && (
          <div className="actions">
            <CommandButton name="abandon-pick" label="Abandon a pick by app id…" />
          </div>
        )}
      </Card>
    </>
  )
}
