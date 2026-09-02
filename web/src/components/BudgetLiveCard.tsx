import { fmtAgo } from '../format'
import type { BudgetSession } from '../types'

interface Props {
  session: BudgetSession
}

const VERDICT_LABELS: Record<string, string> = {
  engaged: 'Billing — you are playing',
  not_applicable: 'Not billing — no game running',
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
      {session.billing_label && (
        <p className="hint">
          {/* The assignment above is what the enforcer told you to play; this
              is what the budget charged. A counted non-Steam game is never the
              assignment, so the two legitimately differ. The key is the *last*
              one credited, so it must not claim to be live once nothing
              qualifies any more. */}
          {session.state === 'engaged' ? 'Billing to ' : 'Last billed to '}
          <strong>{session.billing_label}</strong>
        </p>
      )}
      <p className="hint">
        {/* The daemon logs on change or a 5-minute heartbeat, so this reading
            can legitimately be minutes old. Saying so beats implying "now". */}
        as of {fmtAgo(session.observed_at)}
      </p>
    </section>
  )
}
