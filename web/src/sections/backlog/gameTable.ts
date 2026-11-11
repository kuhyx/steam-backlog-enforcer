// <game-table>: the backlog-completion planner page (was PlannerView,
// FilterPanel and GameTable). The element only loads the dataset, shows
// loading / error states and re-reads a hand-edited hash; the planner
// itself lives in planner.ts.

import { q } from '../../api/queries'
import { h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { commandLine, errorNotice, loading } from '../../ui/build'
import { Planner } from './planner'

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
      // Textgate: ⛔ + the server's own message + the recovery command; the
      // explanation is spoken only (errorNotice).
      this.replaceChildren(
        h('div', { class: 'status' }, error ? errorNotice(error, commandLine('./run.sh serve')) : loading('backlog')),
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
