import { useQuery } from '@tanstack/react-query'
import { q } from '../api/queries'
import { CommandCard } from '../commands/CommandCard'
import { Notice } from '../ui/Notice'
import { Actions, PageHead } from '../ui/Page'

export function Store() {
  const { data } = useQuery(q.status)
  return (
    <>
      <PageHead title="Store" sub="The Steam store is blocked by default. Every way through it is capped and logged." />
      {data && (
        <Notice tone={data.store_blocked ? 'info' : 'warning'} title={data.store_blocked ? 'Store blocked' : 'Store unblocked'}>
          {data.store_blocked
            ? 'Unblocking takes a typed phrase and is capped at 30 minutes.'
            : 'The store is open right now; it re-blocks automatically.'}
        </Notice>
      )}
      <Actions>
        <CommandCard name="unblock" label="Unblock…" />
        <CommandCard name="buy-dlc" label="Buy DLC…" />
        <CommandCard name="add-exception" label="Request exception…" />
      </Actions>
    </>
  )
}
