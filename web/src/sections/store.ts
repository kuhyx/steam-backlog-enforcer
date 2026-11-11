// Store page section (was screens/Store.tsx): whether the store is blocked
// right now. Nothing shows until the status is known.

import { q } from '../api/queries'
import { define, h } from '../lib/dom'
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
    // Textgate: 🛒 + lock state painted (tone is the 2nd channel), the sentence spoken.
    const [tone, icon, spoken] = data.store_blocked
      ? (['info', '🛒🔒', 'Store blocked. Unblocking takes a typed phrase and is capped at 30 minutes.'] as const)
      : (['warning', '🛒🔓', 'Store unblocked. The store is open right now; it re-blocks automatically.'] as const)
    const el = notice(tone, null, h('span', { 'aria-hidden': 'true' }, icon), h('span', { class: 'sr-only' }, spoken))
    el.dataset.blocked = String(data.store_blocked)
    this.replaceChildren(el)
  }
}

define('store-notice', StoreNoticeElement)
