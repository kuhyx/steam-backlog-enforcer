import { seriesClass } from '../budgetSeries'
import { fmtDuration } from '../format'
import type { BudgetLegendEntry, BudgetToday } from '../types'

interface Props {
  today: BudgetToday
  legend: BudgetLegendEntry[]
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

export function BudgetTodayCard({ today, legend, maskedCount }: Props) {
  // Colour by the chart's legend position so a game reads the same in both
  // places; today can hold games the capped 14-day legend left out, and those
  // fall back to their own row order.
  const indexFor = new Map(legend.map((e, i) => [e.key, i]))

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
      {today.games.length > 0 && (
        <>
          <h3 className="budget-subhead">Today by game</h3>
          <ul className="budget-games">
            {today.games.map((game, i) => (
              <li key={game.key}>
                <span
                  className={`swatch ${seriesClass(game.key, indexFor.get(game.key) ?? i)}`}
                  aria-hidden="true"
                />
                <span className="budget-game-name">{game.label}</span>
                <span className="budget-game-time">{fmtDuration(game.seconds)}</span>
                <span className="budget-game-share">
                  {Math.round(game.fraction * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
