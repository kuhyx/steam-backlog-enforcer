// `<setup-card>` (was SetupCard in screens/System.tsx): whether setup is
// done, without ever showing the key.

import { q } from '../../api/queries'
import { define, h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { pageHref } from '../../lib/runner'
import { card, facts, glyph, link } from '../../ui/build'

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
          [glyph('syssetup.configured', 'Configured'), data ? (data.configured ? glyph('state.yes', 'Yes') : glyph('state.no', 'No')) : '…'],
          [glyph('setup.api-key', 'Steam API key'), data ? (data.has_api_key ? glyph('setup.key-stored','Stored (never shown)') : glyph('state.no', 'Missing')) : '…'],
          [glyph('setup.steam-id', 'Steam ID'), h('span', { class: 'mono' }, data?.steam_id ?? '—')],
        ]),
        { aside: link(pageHref('/setup'), glyph('syssetup.edit', 'Open setup')), icon: 'cmd.setup' },
      ),
    )
  }
}

define('setup-card', SetupCardElement)
