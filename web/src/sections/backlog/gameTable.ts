// <game-table>: the backlog-completion planner page (was PlannerView,
// FilterPanel and GameTable). The element only loads the dataset, shows
// loading / error states and re-reads a hand-edited hash; the planner
// itself lives in planner.ts.

import { q } from '../../api/queries'
import { h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { Planner } from './planner'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export class GameTableElement extends LiveElement {
  private planner: Planner | null = null

  protected override setup(): void {
    this.watch(q.dataset)
    const onHash = () => { this.planner?.restore() }
    window.addEventListener('hashchange', onHash)
    this.onCleanup(() => { window.removeEventListener('hashchange', onHash) })
  }

  protected update(): void {
    const { data, error } = q.dataset.state
    if (!data) {
      this.planner = null
      this.replaceChildren(
        error
          ? h(
              'div',
              { class: 'status' },
              h('p', { class: 'error' }, `Could not load data: ${message(error)}`),
              h('p', { class: 'hint' }, 'Is the backend running? Start it with ', h('code', {}, './run.sh serve'), '.'),
            )
          : h('div', { class: 'status' }, h('p', { class: 'hint' }, 'Loading your backlog…')),
      )
      return
    }
    if (this.planner) {
      this.planner.setData(data)
      return
    }
    this.planner = new Planner(data)
    this.replaceChildren(...this.planner.nodes)
  }
}
