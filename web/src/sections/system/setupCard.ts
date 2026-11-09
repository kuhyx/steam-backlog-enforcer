// `<setup-card>` (was SetupCard in screens/System.tsx): whether setup is
// done, without ever showing the key.

import { q } from '../../api/queries'
import { define, h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { pageHref } from '../../lib/runner'
import { card, facts, link } from '../../ui/build'

export class SetupCardElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.setup)
  }

  protected update(): void {
    const data = q.setup.state.data
    this.replaceChildren(
      card(
        'Setup',
        facts([
          ['Configured', data ? (data.configured ? 'Yes' : 'No') : '…'],
          ['Steam API key', data ? (data.has_api_key ? 'Stored (never shown)' : 'Missing') : '…'],
          ['Steam ID', h('span', { class: 'mono' }, data?.steam_id ?? '—')],
        ]),
        { aside: link(pageHref('/setup'), 'Open setup') },
      ),
    )
  }
}

define('setup-card', SetupCardElement)
