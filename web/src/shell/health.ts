// `<health-badges>` (server + daemon pills) and `<stale-banner>` (shown on
// every page while the running server is older than the code on disk).

import { q } from '../api/queries'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { errorNotice } from '../ui/build'
import { ServerRestart } from './serverRestart'

const DAEMON_TONE = { running: 'success', restarting: 'warning', unreachable: 'danger' } as const

export class HealthBadgesElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.server)
    this.watch(q.daemon)
  }

  protected update(): void {
    const server = q.server.state
    const d = q.daemon.state.data?.state
    const serverTone = server.error ? 'danger' : server.data?.stale ? 'warning' : 'success'
    const serverText = server.error ? 'Server down' : server.data?.stale ? 'Server stale' : 'Server ok'
    this.replaceChildren(
      h(
        'div',
        { class: 'health', 'aria-label': 'Health' },
        h('span', { class: `pill pill-${serverTone}`, title: server.data ? `v${server.data.version}` : null }, serverText),
        h('span', { class: `pill pill-${d ? DAEMON_TONE[d] : 'neutral'}` }, `Daemon ${d ?? '…'}`),
      ),
    )
  }
}

export class StaleBannerElement extends LiveElement {
  private restart = new ServerRestart(() => {
    this.update()
  })

  protected override setup(): void {
    this.watch(q.server)
    this.onCleanup(() => {
      this.restart.dispose()
    })
  }

  protected update(): void {
    if (!q.server.state.data?.stale) {
      this.replaceChildren()
      return
    }
    const { action } = this.restart
    this.replaceChildren(
      h(
        'div',
        { class: 'banner banner-warning', role: 'status' },
        h('span', {}, h('strong', {}, 'The web server is running stale code.'), ' Restart it to pick up the new version.'),
        h(
          'button',
          {
            type: 'button',
            class: 'btn btn-primary btn-small',
            disabled: this.restart.restarting || action.pending,
            onclick: () => void action.run(),
          },
          this.restart.restarting ? 'Restarting…' : 'Restart server',
        ),
        action.error ? errorNotice(action.error) : null,
      ),
    )
  }
}

define('health-badges', HealthBadgesElement)
define('stale-banner', StaleBannerElement)
