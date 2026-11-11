// `<server-card>` (was screens/system/ServerCard.tsx): the unprivileged web
// server's health and restart. The restart button is built once, so a
// health poll never takes focus off it.

import { q } from '../../api/queries'
import { define, h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { ServerRestart } from '../../shell/serverRestart'
import { card, errorNotice, facts, glyph, loading, notice } from '../../ui/build'
import { ago, dateTime } from '../../ui/format'

export class ServerCardElement extends LiveElement {
  private readonly info = h('div', { class: 'contents' })
  private readonly failure = h('div', { class: 'contents' })
  private readonly button = h('button', {
    type: 'button',
    class: 'btn btn-ghost',
    onclick: () => {
      void this.restart.action.run()
    },
  })
  private readonly root = card('Web server', [this.info, this.failure, h('div', { class: 'actions' }, this.button)], { icon: '🌐' })
  private readonly restart = new ServerRestart(() => {
    this.update()
  })

  protected override setup(): void {
    this.replaceChildren(this.root)
    this.watch(q.server)
    this.onCleanup(() => {
      this.restart.dispose()
    })
  }

  protected update(): void {
    const { data, error } = q.server.state
    this.info.replaceChildren(
      ...(error ? [errorNotice(error)] : []),
      ...(!data && !error ? [loading('server health')] : []),
      ...(data?.stale ? [notice('warning', null, h('span', { class: 'sr-only' }, h('strong', {}, 'Stale'), ' The code on disk is newer than this process.'))] : []),
      ...(data
        ? [
            facts([
              [glyph('🏷️', 'Version'), h('span', { class: 'mono' }, data.version)],
              [glyph('🕒', 'Started'), h('span', { 'aria-label': `${dateTime(data.started_at)} (${ago(data.started_at)})` }, dateTime(data.started_at))],
              [glyph('💾', 'Code'), data.stale ? glyph('⚠️', 'stale') : glyph('✅', 'current')],
            ]),
          ]
        : []),
    )
    const { action, restarting } = this.restart
    this.failure.replaceChildren(...(action.error ? [errorNotice(action.error)] : []))
    this.button.disabled = restarting || action.pending
    this.button.dataset.restarting = String(restarting)
    this.button.replaceChildren(restarting ? glyph('⏳', 'Restarting… the page reloads when it is back') : glyph('🔄', 'Restart server'))
  }
}

define('server-card', ServerCardElement)
