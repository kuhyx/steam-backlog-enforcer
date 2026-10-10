import { Link } from '@tanstack/react-router'
import { CommandCard } from '../commands/CommandCard'
import { BudgetPanel } from '../components/BudgetPanel'
import { Actions, PageHead } from '../ui/Page'

/**
 * `gaming-status` (the live budget panel) plus every gaming control. `?demo=1`
 * points the panel at the short-budget demo run, the only way to watch the
 * cutoff engage without spending a real day.
 */
export function Gaming({ demo }: { demo: boolean }) {
  return (
    <>
      <PageHead title="Gaming" sub="Today's budget, what is billing right now, and the last two weeks.">
        <Link to="/gaming" search={{ demo: !demo }} className="btn btn-ghost">
          {demo ? 'Show production budget' : 'Show demo budget'}
        </Link>
      </PageHead>
      <Actions>
        <CommandCard name="gaming-reset" label="Reset today…" />
        <CommandCard name="block-gaming" label="Block gaming…" />
        <CommandCard name="gaming-unblock" label="Release mounts…" />
      </Actions>
      <BudgetPanel demo={demo} />
    </>
  )
}
