// Picks page sections (was screens/Picks.tsx): everything that changes
// which game is assigned.

import { q } from '../api/queries'
import { commandButton } from '../commands/commandButton'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { card, empty, errorNotice, loading } from '../ui/build'

/** Page subtitle: the assigned game, once known. */
export class PicksSubElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const name = q.status.state.data?.current_game_name
    this.replaceChildren(...(name ? ['Assigned: ', h('strong', {}, name)] : ['Which game you are playing, and how to move on.']))
  }
}

export class ManualPicksElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const { data, error } = q.status.state
    const none = data?.manual_picks.length === 0 && data.kept_picks.length === 0
    const abandon = (app_id: number) =>
      commandButton({ name: 'abandon-pick', preset: { app_id }, label: 'Abandon…', tone: 'danger' })
    this.replaceChildren(
      card('Manual picks', [
        error ? errorNotice(error) : null,
        !data && !error ? loading('status') : null,
        none ? empty('No manual picks. "Lock in a game" adds one and locks most commands for 14 days.') : null,
        h(
          'ul',
          { class: 'rows' },
          (data?.manual_picks ?? []).map((p) =>
            h(
              'li',
              { class: 'row' },
              h('span', { class: 'grow' }, h('strong', {}, p.name), ' ', h('span', { class: 'muted' }, `· picked ${p.age_days} d ago · ${p.app_id}`)),
              abandon(p.app_id),
            ),
          ),
          // Released, expired or kept by "Pick…": still installed and playable.
          (data?.kept_picks ?? []).map((p) =>
            h(
              'li',
              { class: 'row' },
              h('span', { class: 'grow' }, h('strong', {}, p.name), ' ', h('span', { class: 'muted' }, `· kept · no lock · ${p.app_id}`)),
              abandon(p.app_id),
            ),
          ),
        ),
        none
          ? h('div', { class: 'actions' }, commandButton({ name: 'abandon-pick', label: 'Abandon a pick by app id…' }))
          : null,
      ]),
    )
  }
}

define('picks-sub', PicksSubElement)
define('manual-picks', ManualPicksElement)
