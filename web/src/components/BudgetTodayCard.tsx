import { fmtDuration } from '../format'
import type { BudgetToday } from '../types'

interface Props {
  today: BudgetToday
  maskedCount: number
}

/** Which colour the meter takes: normal, into the warning band, or spent.
 *
 * Keyed on warnings already fired rather than on `next_warning_seconds`: that
 * field is by construction always *below* the remaining time, so comparing the
 * two could never turn the meter amber. "The enforcer has warned you" is also
 * the thing the colour is actually trying to say.
 */
function meterState(today: BudgetToday): string {
  if (today.blocked) return 'blocked'
  return today.warned_seconds.length > 0 ? 'warn' : 'ok'
}

export function BudgetTodayCard({ today, maskedCount }: Props) {
  return (
    <section className="budget-today">
      <h2>Today</h2>
      <p className="budget-hero">
        <strong>{fmtDuration(today.seconds_remaining)}</strong> left
      </p>
      <div className={`budget-meter budget-meter--${meterState(today)}`}>
        <div
          className="budget-meter-fill"
          style={{ width: `${(today.fraction_used * 100).toFixed(1)}%` }}
        />
      </div>
      <p className="hint">
        {fmtDuration(today.seconds_used)} of {fmtDuration(today.budget_seconds)} used
        {' · '}
        {Math.round(today.fraction_used * 100)}%{' · '}
        gaming day {today.gaming_day} (starts {today.day_starts_at})
      </p>
      <p className="hint">
        {today.blocked ? (
          <span className="budget-badge budget-badge--blocked">
            {/* Read the live mount count rather than inferring it from
                `blocked`: the total-block branch releases every mount while
                leaving `blocked_at` set, so the two can genuinely disagree —
                and a badge claiming a mask that is not there is the one thing
                this panel must never do. */}
            {maskedCount > 0
              ? 'Cutoff engaged — launchers are masked'
              : 'Cutoff engaged — launchers are not currently masked'}
          </span>
        ) : today.next_warning_seconds === null ? (
          'No further warnings today.'
        ) : (
          `Next warning at ${fmtDuration(today.next_warning_seconds)} remaining.`
        )}
      </p>
    </section>
  )
}
