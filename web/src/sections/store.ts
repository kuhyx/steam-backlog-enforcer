// Store page section (was screens/Store.tsx): whether the store is blocked
// right now. Nothing shows until the status is known.

import { q } from '../api/queries'
import { define } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { notice } from '../ui/build'

export class StoreNoticeElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.status)
  }

  protected update(): void {
    const data = q.status.state.data
    if (!data) {
      this.replaceChildren()
      return
    }
    this.replaceChildren(
      data.store_blocked
        ? notice('info', 'Store blocked', 'Unblocking takes a typed phrase and is capped at 30 minutes.')
        : notice('warning', 'Store unblocked', 'The store is open right now; it re-blocks automatically.'),
    )
  }
}

define('store-notice', StoreNoticeElement)
