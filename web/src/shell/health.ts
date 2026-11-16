// `<health-badges>` (server + daemon pills) and `<stale-banner>` (shown on
// every page while the running server is older than the code on disk).

import { q } from '../api/queries'
import type { IconId } from '../icons/registry'
import { iconInline } from '../icons/render'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { errorNotice, glyph } from '../ui/build'
import { ServerRestart } from './serverRestart'

const DAEMON_TONE = { running: 'success', restarting: 'warning', unreachable: 'danger' } as const
const STATE_ICON: Record<string, IconId> = { success: 'health.ok', warning: 'health.warn', danger: 'health.bad', neutral: 'health.unknown' }

/** A health pill: the subject and state icons painted, `text` (+ `extra`) spoken. `data-state` holds the words for tests. */
function badge(tone: string, subject: IconId, text: string, extra = ''): HTMLSpanElement {
  return h(
    'span',
    { class: `pill pill-${tone}`, 'data-state': text },
    h('span', { class: 'has-word', 'aria-hidden': 'true' }, iconInline(subject), iconInline(STATE_ICON[tone] ?? 'health.unknown')),
    h('span', { class: 'sr-only' }, text + extra),
  )
}

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
    // Textgate: the server / daemon icon + a state icon, on the tone colour;
    // the words (and the version, formerly a tooltip) are spoken only.
    const version = server.data ? ` v${server.data.version}` : ''
    this.replaceChildren(
      h(
        'div',
        { class: 'health', 'aria-label': 'Health' },
        badge(serverTone, 'server.heading', serverText, version),
        badge(d ? DAEMON_TONE[d] : 'neutral', 'daemon.heading',`Daemon ${d ?? '…'}`),
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
        glyph('health.stale', 'The web server is running stale code. Restart it to pick up the new version.'),
        h(
          'button',
          {
            type: 'button',
            class: 'btn btn-primary btn-small',
            disabled: this.restart.restarting || action.pending,
            onclick: () => void action.run(),
            'aria-label': this.restart.restarting ? 'Restarting…' : 'Restart server',
          },
          iconInline(this.restart.restarting ? 'state.wait' : 'server.restart'),
        ),
        action.error ? errorNotice(action.error) : null,
      ),
    )
  }
}

define('health-badges', HealthBadgesElement)
define('stale-banner', StaleBannerElement)
