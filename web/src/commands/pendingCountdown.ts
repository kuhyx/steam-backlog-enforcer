// Armed countdown (gaming-reset), was PendingCountdown.tsx: heartbeats at
// half the server's interval so one slow request never lapses it, a
// countdown driven by the server's `ready_at` (not a local timer), then the
// phrase is retyped to commit. Closing the page drops the action with a
// keepalive DELETE.

import { api, ApiFailure } from '../api/client'
import type { Job, PendingAction } from '../api/jobContract'
import { progressBar } from '../jobs/progress'
import { Action } from '../lib/action'
import { h } from '../lib/dom'
import { errorNotice, notice } from '../ui/build'
import { clock } from '../ui/format'
import { phraseMatches } from './catalog'
import { PhraseField } from './phraseField'

/**
 * The daemon checks `ready_at` on its own clock; unlocking the commit a
 * second late keeps a slightly fast browser clock from offering a commit the
 * daemon refuses (seen in vmbox: refused 34 ms early, countdown_running).
 */
export const CLOCK_SLACK_MS = 1000

/** ⚠️ 🚪: leaving cancels the countdown; the sentence is spoken only. */
function stayNotice(): HTMLDivElement {
  const el = notice('warning', null, h('span', { 'aria-hidden': 'true' }, '🚪✖️'))
  el.setAttribute('aria-label', 'Closing this dialog, navigating away or closing the tab cancels the countdown.')
  return el
}

export interface CountdownCallbacks {
  onCommitted: (job: Job) => void
  onCancel: () => void
  onRearm: () => void
}

export class PendingCountdown {
  readonly el = h('div', { class: 'stack countdown' })
  private pending: PendingAction
  private lastBeat = Date.now()
  private beatError: unknown = null
  private phrase: PhraseField | null = null
  private readonly commit: Action<[string], Job>
  private readonly cancel: Action<[], void>
  private readonly cb: CountdownCallbacks
  private readonly timers: ReturnType<typeof setInterval>[] = []
  private readonly drop = () => {
    void api.dropPending(this.pending.id, true).catch(() => undefined)
  }
  private shownReady: boolean | null = null
  private commitForm: { submit: HTMLButtonElement; errors: HTMLDivElement } | null = null
  private readonly parts = {
    num: h('span', { class: 'countdown-num' }),
    caption: h('span', { class: 'muted' }),
    bar: h('div', { class: 'contents' }),
    beat: h('p', { class: 'field-help' }),
    live: h('p', { class: 'sr-only', 'aria-live': 'polite' }),
    body: h('div', { class: 'contents' }),
  }

  constructor(pending: PendingAction, cb: CountdownCallbacks) {
    this.pending = pending
    this.cb = cb
    this.commit = new Action((phrase: string) => api.commit(this.pending.id, phrase), () => {
      this.renderBody(true)
    })
    this.cancel = new Action(() => api.dropPending(this.pending.id), () => {
      this.renderBody(this.shownReady === true)
    })
    const everyMs = Math.max(1000, (pending.heartbeat_interval_seconds * 1000) / 2)
    this.timers.push(
      setInterval(() => {
        api.heartbeat(pending.id).then(
          (p) => {
            this.pending = p
            this.lastBeat = Date.now()
            this.beatError = null
          },
          (e: unknown) => {
            this.beatError = e
            this.tick()
          },
        )
      }, everyMs),
      setInterval(() => {
        this.tick()
      }, 250),
    )
    window.addEventListener('pagehide', this.drop)
    this.el.append(
      h('div', { class: 'countdown-clock', 'aria-live': 'off' }, this.parts.num, this.parts.caption),
      this.parts.bar,
      this.parts.beat,
      this.parts.live,
      this.parts.body,
    )
    this.tick()
  }

  /** Stop heartbeats and timers (the dialog closed or moved on). */
  dispose(): void {
    for (const t of this.timers) clearInterval(t)
    window.removeEventListener('pagehide', this.drop)
  }

  private tick(): void {
    if (this.beatError instanceof ApiFailure && this.beatError.code === 'pending_lapsed') {
      this.dispose()
      this.el.className = 'stack'
      this.el.replaceChildren(
        errorNotice(this.beatError),
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'btn btn-primary', autofocus: true, 'aria-label': 'Arm again', onclick: this.cb.onRearm }, '🔁')),
      )
      this.el.querySelector<HTMLElement>('[autofocus]')?.focus()
      return
    }
    const now = Date.now()
    const armed = Date.parse(this.pending.armed_at)
    const ready = Date.parse(this.pending.ready_at) + CLOCK_SLACK_MS
    const left = Math.max(0, (ready - now) / 1000)
    const isReady = left <= 0
    this.parts.num.textContent = clock(left)
    // Textgate: 🔓/🔒 painted beside the clock; 💓 + seconds since the last
    // heartbeat (red 💔 when failing). Sentences are spoken only.
    this.parts.caption.replaceChildren(
      h('span', { 'aria-hidden': 'true' }, isReady ? '🔓' : '🔒'),
      h('span', { class: 'sr-only' }, isReady ? 'Ready to commit' : 'until commit unlocks'),
    )
    this.parts.bar.replaceChildren(progressBar(Math.min(1, (now - armed) / (ready - armed)), 'Countdown', isReady ? 'success' : 'warning'))
    const sinceBeat = Math.round((now - this.lastBeat) / 1000)
    const failing = this.beatError !== null
    this.parts.beat.replaceChildren(
      h('span', { 'aria-hidden': 'true', class: failing ? 'text-danger' : '' }, `${failing ? '💔' : '💓'} ${sinceBeat}s`),
      h(
        'span',
        { class: 'sr-only' },
        `Keep this window open. Heartbeat every ${Math.round(this.pending.heartbeat_interval_seconds / 2)} s · last ${sinceBeat} s ago`,
        failing ? ' · heartbeat failing, retrying' : '',
      ),
    )
    this.parts.live.textContent = isReady ? 'Countdown finished. Retype the phrase to commit.' : ''
    if (isReady !== this.shownReady) this.renderBody(isReady)
  }

  private renderBody(isReady: boolean): void {
    const first = this.shownReady !== isReady
    this.shownReady = isReady
    if (!isReady) {
      this.parts.body.replaceChildren(
        stayNotice(),
        h(
          'div',
          { class: 'actions' },
          h(
            'button',
            { type: 'button', class: 'btn btn-ghost', autofocus: true, 'aria-label': this.cancel.pending ? 'Cancelling…' : 'Cancel countdown', onclick: () => void this.doCancel() },
            this.cancel.pending ? '⏳' : '✖️',
          ),
        ),
      )
      return
    }
    if (first || !this.phrase) {
      const submitBtn = h('button', { type: 'submit', class: 'btn btn-danger' })
      const errorSlot = h('div', { class: 'contents' })
      this.phrase = new PhraseField({
        phrase: this.pending.phrase,
        autofocus: true,
        label: 'Retype the phrase to commit',
        onChange: () => {
          this.renderBody(true)
        },
      })
      const form = h(
        'form',
        { class: 'stack' },
        this.phrase.el,
        errorSlot,
        h('div', { class: 'actions' }, submitBtn, h('button', { type: 'button', class: 'btn btn-ghost', 'aria-label': 'Cancel', onclick: () => void this.doCancel() }, '✖️')),
      )
      form.addEventListener('submit', (e) => {
        e.preventDefault()
        if (this.phrase && phraseMatches(this.pending.phrase, this.phrase.value)) void this.doCommit(this.phrase.value)
      })
      this.parts.body.replaceChildren(form)
      this.commitForm = { submit: submitBtn, errors: errorSlot }
      this.phrase.input.focus()
    }
    const { submit, errors } = this.commitForm as { submit: HTMLButtonElement; errors: HTMLDivElement }
    submit.disabled = !phraseMatches(this.pending.phrase, this.phrase.value) || this.commit.pending
    submit.textContent = this.commit.pending ? '⏳' : '✔️'
    submit.setAttribute('aria-label', this.commit.pending ? 'Committing…' : 'Commit')
    errors.replaceChildren(...(this.commit.error ? [errorNotice(this.commit.error)] : []))
  }

  private async doCommit(phrase: string): Promise<void> {
    const out = await this.commit.run(phrase)
    if (out.ok) {
      this.dispose()
      this.cb.onCommitted(out.value)
    }
  }

  private async doCancel(): Promise<void> {
    await this.cancel.run()
    this.dispose()
    this.cb.onCancel()
  }
}
