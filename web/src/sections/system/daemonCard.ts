// `<daemon-card>` (was screens/system/DaemonCard.tsx): the root daemon's
// state, live journal tail, rate-limited restart and the 60 s demo run.
// Deliberately no stop/disable: the contract has none. The frame is built
// once and only its parts change, so the 1 s countdown tick never steals
// focus from a button or yanks the journal while it is being read.

import { q } from '../../api/queries'
import type { IconId } from '../../icons/registry'
import { iconInline } from '../../icons/render'
import { define, h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { runner } from '../../lib/runner'
import type { DaemonState } from '../../api/contract'
import { card, commandLine, errorNotice, facts, glyph, loading, notice } from '../../ui/build'
import { ago, clock } from '../../ui/format'

/** "3 h ago" painted as "3 h" (a number + unit), the full phrase spoken. */
function since(iso: string): HTMLSpanElement {
  const full = ago(iso)
  const painted = full === 'just now' ? '0 min' : full.replace(/ ago$/, '')
  return h('span', { 'aria-label': full }, h('span', { 'aria-hidden': 'true' }, painted))
}

/** Milliseconds left on the restart rate limit; 0 when free. */
export function restartWaitMs(availableAt: string | null, now: number = Date.now()): number {
  return availableAt ? Math.max(0, Date.parse(availableAt) - now) : 0
}

/** Daemon state: glyph painted, the state word spoken. */
const STATE_ICON = {
  running: 'daemon.running',
  restarting: 'daemon.restarting',
  unreachable: 'daemon.unreachable',
} as const satisfies Record<DaemonState, IconId>

function unreachableNotice(): HTMLDivElement {
  // Textgate: ⛔ + the command to run are painted; the explanation is spoken only.
  return notice(
    'danger',
    null,
    h(
      'span',
      { class: 'sr-only' },
      h('strong', {}, 'Daemon unreachable'),
      ' Privileged actions (store unblock, gaming reset/block/unblock, restart) are unavailable. Check it from a terminal:',
    ),
    commandLine('systemctl status steam-backlog-enforcer'),
  )
}

export class DaemonCardElement extends LiveElement {
  private readonly status = h('div', { class: 'contents' })
  private readonly body = h('div', { class: 'contents' })
  private readonly alert = h('div', { class: 'contents' })
  private readonly factsSlot = h('div', { class: 'contents' })
  private readonly journal = h('pre', { class: 'journal', tabindex: 0, 'aria-label': 'Daemon journal (live)' })
  private readonly restart = h('button', {
    type: 'button',
    class: 'btn btn-ghost',
    onclick: () => {
      if (this.canRestart) runner.run('enforce', { demo: 0 })
    },
  })
  // enforce is a "screen" command, so commandButton would link back to this
  // page; open the runner directly, as restart does.
  private readonly demo = h(
    'button',
    {
      type: 'button',
      class: 'btn btn-ghost',
      onclick: () => {
        runner.run('enforce', { demo: 1 })
      },
    },
    glyph('daemon.demo_run', 'Demo run (enforce --demo)…'),
  )
  private readonly parts = [
    this.alert,
    this.factsSlot,
    h('div', { class: 'actions' }, this.restart, this.demo),
    h('h3', { class: 'h3' }, glyph('daemon.journal', 'Journal')),
    this.journal,
  ]
  private readonly root = card('Enforcer daemon', [this.status, this.body], { icon: 'daemon.heading' })
  private shown = false
  private canRestart = false
  private unreachable = false

  protected override setup(): void {
    this.replaceChildren(this.root)
    this.watch(q.daemon)
    this.tick(1000)
  }

  protected update(): void {
    const { data, error } = q.daemon.state
    this.status.replaceChildren(...(error ? [errorNotice(error)] : !data ? [loading('daemon status')] : []))
    const show = !error && data !== undefined
    if (show !== this.shown) {
      this.shown = show
      this.body.replaceChildren(...(show ? this.parts : []))
    }
    if (!show) return
    const waitMs = restartWaitMs(data.restart_available_at)
    // Rebuilt only on a change, so the Copy button keeps focus and its "Copied".
    const unreachable = data.state === 'unreachable'
    if (unreachable !== this.unreachable) {
      this.unreachable = unreachable
      this.alert.replaceChildren(...(unreachable ? [unreachableNotice()] : []))
    }
    this.factsSlot.replaceChildren(
      facts([
        [glyph('daemon.state', 'State'), h('span', { 'data-state': data.state }, glyph(STATE_ICON[data.state], data.state))],
        [glyph('daemon.pid', 'PID'), data.pid ?? '—'],
        [glyph('daemon.up_since', 'Up since'), data.started_at ? since(data.started_at) : '—'],
      ]),
    )
    this.canRestart = waitMs === 0 && data.state === 'running'
    this.restart.setAttribute('aria-disabled', String(!this.canRestart))
    // Rate limited: the busy icon + the clock counting down; free: the restart icon. Words spoken only.
    const wait = clock(waitMs / 1000)
    this.restart.replaceChildren(
      waitMs > 0
        ? h('span', { 'aria-label': `Restart available in ${wait}` }, h('span', { 'aria-hidden': 'true' }, iconInline('state.wait'), ` ${wait}`))
        : glyph('daemon.restart', 'Restart daemon…'),
    )
    this.fillJournal(data.journal_tail)
  }

  /** New text only when it changed; follow the tail unless scrolled up. */
  private fillJournal(lines: string[]): void {
    // The journal lines are the daemon's own log (content); empty paints a dash.
    const text = lines.length ? lines.join('\n') : '—'
    const j = this.journal
    if (j.textContent === text) return
    const following = j.scrollHeight - j.scrollTop - j.clientHeight < 8
    j.textContent = text
    if (following) j.scrollTop = j.scrollHeight
  }
}

define('daemon-card', DaemonCardElement)
