// The small painted parts of the runner form: the command's flags, the lock
// notice, the "fill the fields" hint and the terminal fallback. Every icon is
// a registered id, so the user's word and glyph apply; each sentence is
// spoken only (aria-label / pill text).

import type { CommandSpec } from '../api/contract'
import { iconInline } from '../icons/render'
import { h } from '../lib/dom'
import { commandLine, notice, pill } from '../ui/build'

/** The countdown flag plus the minutes (a number, so painted); the word is spoken only. */
function countdownPill(seconds: number): HTMLSpanElement {
  const minutes = Math.round(seconds / 60)
  const el = pill('warning', `${minutes} min countdown`, 'cmdflag.countdown')
  el.append(h('span', { class: 'pill-num', 'aria-hidden': 'true' }, `${minutes}′`))
  return el
}

/** What the command is: root, state-changing or read-only, cancellable, countdown. */
export function commandFlags(spec: CommandSpec): (HTMLSpanElement | null)[] {
  const countdown = spec.friction?.countdown_seconds
  return [
    spec.privileged ? pill('neutral', 'Runs as root via the daemon', 'cmdflag.root') : null,
    spec.mutating ? pill('neutral', 'Changes state', 'cmdflag.mutating') : pill('neutral', 'Read-only', 'cmdflag.readonly'),
    spec.cancellable ? pill('neutral', 'Cancellable', 'cmdflag.cancellable') : null,
    countdown ? countdownPill(countdown) : null,
  ]
}

/** Warning notice painted with the lock mark; the server's lock reason is spoken only. */
export function lockedNotice(reason: string): HTMLDivElement {
  const el = notice('warning', null)
  const mark = iconInline('state.locked', 'notice-icon')
  if (mark.classList.contains('icon-inline')) mark.classList.add('notice-mark')
  el.firstElementChild?.replaceWith(mark)
  el.setAttribute('aria-label', `Locked: ${reason}`)
  return el
}

/** Info notice: fill the fields above first; the sentence is spoken only. */
export function fillHint(missing: readonly string[]): HTMLDivElement {
  const hint = notice('info', null, iconInline('runner.fill'))
  hint.setAttribute('aria-label', `Fill in the fields above to see the exact phrase (${missing.join(', ')}).`)
  return hint
}

/** The terminal command to run when the daemon cannot be reached. */
export function terminalFallback(command: string): HTMLElement[] {
  return [h('p', { class: 'm0', 'aria-label': 'Run it from a terminal instead:' }, iconInline('runner.terminal')), commandLine(command)]
}
