import { useBudgetPoll } from '../useBudgetPoll'
import { BudgetHistoryChart } from './BudgetHistoryChart'
import { BudgetLiveCard } from './BudgetLiveCard'
import { BudgetRulesCard } from './BudgetRulesCard'
import { BudgetTodayCard } from './BudgetTodayCard'

interface Props {
  demo: boolean
}

export function BudgetPanel({ demo }: Props) {
  const { data, error } = useBudgetPoll(demo)

  if (error !== null) {
    return (
      <div className="status">
        <p className="error">Could not read budget state: {error}</p>
        <p className="hint">
          Is the backend running? Start it with <code>./run.sh serve</code>.
        </p>
      </div>
    )
  }

  if (data === null) {
    return (
      <div className="status">
        <p className="hint">Reading budget state…</p>
      </div>
    )
  }

  return (
    <main className="content budget">
      {/* A state file we cannot read must say so and still show everything we
          can read — the log, the history and the config are all reachable. */}
      {data.today === null ? (
        <section className="budget-today">
          <h2>Today</h2>
          <p className="error">{data.error ?? 'Budget state unavailable.'}</p>
        </section>
      ) : (
        <BudgetTodayCard today={data.today} legend={data.legend} maskedCount={data.rules.masked_launchers.length} />
      )}
      <BudgetLiveCard session={data.session} />
      <BudgetHistoryChart
        days={data.history}
        legend={data.legend}
        budgetSeconds={data.rules.budget_seconds}
      />
      <BudgetRulesCard rules={data.rules} />
    </main>
  )
}
