// Gaming page elements (was screens/Gaming.tsx, BudgetPanel.tsx and
// useBudgetPoll.ts). `?demo=1` points the panel at the short-budget demo
// run, the only way to watch the cutoff engage without spending a real day.
// The static page is one file for both, so each element reads the URL.

import { explain } from '../../api/errors'
import { q } from '../../api/queries'
import { define, h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { historyCard, liveCard, rulesCard, todayCard, todayUnavailable } from './cards'

/** True on `/gaming/?demo=1` (and the legacy `?demo=true`). */
export function isDemo(search: string = location.search): boolean {
  const demo = new URLSearchParams(search).get('demo')
  return demo === '1' || demo === 'true'
}

/** The page-head toggle between the production and the demo budget. */
export class BudgetModeLinkElement extends LiveElement {
  protected update(): void {
    const demo = isDemo()
    this.replaceChildren(
      h('a', { href: demo ? '/gaming/' : '/gaming/?demo=1', class: 'btn btn-ghost' }, demo ? 'Show production budget' : 'Show demo budget'),
    )
  }
}

/** Live budget: polls every 5 s through `q.budget` / `q.demoBudget`. */
export class BudgetPanelElement extends LiveElement {
  private readonly query = isDemo() ? q.demoBudget : q.budget

  protected override setup(): void {
    this.watch(this.query)
  }

  protected update(): void {
    const { data, error } = this.query.state
    // A failed poll keeps the last data; the error still wins, as it did.
    if (error) {
      this.replaceChildren(
        h(
          'div',
          { class: 'status' },
          h('p', { class: 'error' }, `Could not read budget state: ${explain(error).detail}`),
          h('p', { class: 'hint' }, 'Is the backend running? Start it with ', h('code', {}, './run.sh serve'), '.'),
        ),
      )
      return
    }
    if (!data) {
      this.replaceChildren(h('div', { class: 'status' }, h('p', { class: 'hint' }, 'Reading budget state…')))
      return
    }
    this.replaceChildren(
      h(
        'div',
        { class: 'content budget' },
        // A state file we cannot read must say so and still show everything we
        // can read: the log, the history and the config are all reachable.
        data.today === null ? todayUnavailable(data.error) : todayCard(data.today, data.legend, data.rules.masked_launchers.length),
        liveCard(data.session),
        historyCard(data.history, data.legend, data.rules.budget_seconds),
        rulesCard(data.rules),
      ),
    )
  }
}

define('budget-mode-link', BudgetModeLinkElement)
define('budget-panel', BudgetPanelElement)
