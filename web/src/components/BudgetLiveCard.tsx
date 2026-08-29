import { fmtAgo, fmtDuration } from '../format'
import type { BudgetSession } from '../types'

interface Props {
  session: BudgetSession
}

const VERDICT_LABELS: Record<string, string> = {
  engaged: 'Billing — you are playing',
  paused: 'Not billing — paused',
  not_applicable: 'Not billing — no game running',
}

const CAUSE_LABELS: Record<string, string> = {
  idle: 'no input for longer than the idle grace',
  focus: 'the game window is not focused',
  screen_held: 'the screen is locked or held',
}

function describe(values: string[], labels: Record<string, string>): string[] {
  return values.map((value) => labels[value] ?? value)
}

export function BudgetLiveCard({ session }: Props) {
  if (!session.available) {
    return (
      <section className="budget-live">
        <h2>Right now</h2>
        <p className="hint">No verdict has been logged yet.</p>
      </section>
    )
  }

  return (
    <section className="budget-live">
      <h2>Right now</h2>
      <p>
        <span className={`budget-verdict budget-verdict--${session.state}`}>
          {VERDICT_LABELS[session.state] ?? session.state}
        </span>
      </p>
      {session.qualifying_count > 0 && (
        <p className="hint">
          {session.game_name ? (
            <>
              Assigned game <strong>{session.game_name}</strong> ·{' '}
            </>
          ) : null}
          {session.qualifying_count} qualifying processes
        </p>
      )}
      {session.causes.length > 0 && (
        <p className="hint">Paused because {describe(session.causes, CAUSE_LABELS).join(', ')}.</p>
      )}
      <p className="hint">
        {session.idle_seconds !== null && <>Idle {fmtDuration(session.idle_seconds)} · </>}
        {session.screen_held !== null && <>Screen held: {session.screen_held ? 'yes' : 'no'} · </>}
        {/* The daemon logs on change or a 5-minute heartbeat, so this reading
            can legitimately be minutes old. Saying so beats implying "now". */}
        as of {fmtAgo(session.observed_at)}
      </p>
    </section>
  )
}
