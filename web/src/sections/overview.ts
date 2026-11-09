// `<backlog-overview>`: the dashboard's view of the backlog planner at the
// CLI default filters, so the summary cards and the completion timeline are
// visible without opening Backlog. Read-only: filtering and the game table
// stay on the Backlog page, which the card links to.

import { q } from '../api/queries'
import { applyFilters } from '../estimate'
import { timelineChart } from '../lib/charts/timeline'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { card, errorNotice, link, loading } from '../ui/build'
import { defaultFilters } from './backlog/plannerFilters'
import { summaryCards } from './backlog/summary'

export class BacklogOverviewElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.dataset)
  }

  protected update(): void {
    const { data, error } = q.dataset.state
    const aside = link('/backlog/', 'Open the planner')
    if (!data) {
      this.replaceChildren(card('Backlog outlook', error ? errorNotice(error) : loading('backlog'), { aside }))
      return
    }
    const filters = defaultFilters(data.defaults)
    const result = applyFilters(data, filters)
    this.replaceChildren(
      card(
        'Backlog outlook',
        h(
          'div',
          // planner-wrap: the cards' container query (2-up when narrow) keys on it.
          { class: 'content planner-wrap' },
          summaryCards({
            result,
            filters,
            state: data.state,
            presets: data.defaults.hours_per_day_presets,
            defaultQualifying: data.default_summary.qualifying,
            paceVsHltb: data.pace_vs_hltb,
          }),
          timelineChart(result, filters, data.state),
        ),
        { aside },
      ),
    )
  }
}

define('backlog-overview', BacklogOverviewElement)
