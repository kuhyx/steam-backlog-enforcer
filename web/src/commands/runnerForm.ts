// The runner dialog's form phase (was the Runner half of RunnerDialog.tsx):
// params, the typed phrase, submit, then hand the next phase (countdown or
// live job) back to <runner-dialog> through RunnerCallbacks.

import { ApiFailure, startJob } from '../api/client'
import type { CommandName, CommandSpec } from '../api/contract'
import { q } from '../api/queries'
import { Action } from '../lib/action'
import { h } from '../lib/dom'
import type { Preset } from '../lib/runner'
import { commandLine, errorNotice, notice, pill } from '../ui/build'
import { fillPhrase, phraseMatches } from './catalog'
import { enforcePreset } from './enforcePreset'
import { gameLookup } from './gameLookup'
import { initialValues, paramError, toParams, type ParamValues } from './params'
import { ParamsForm } from './paramsForm'
import { PendingCountdown } from './pendingCountdown'
import { PhraseField } from './phraseField'

/** Recovery commands the UI offers when the root daemon is down. */
const FALLBACK: Partial<Record<CommandName, string>> = {
  'gaming-unblock': 'sudo ./run.sh gaming-unblock',
}


export type NextPhase = { k: 'pending'; countdown: PendingCountdown } | { k: 'job'; id: string } | { k: 'form'; runner: Runner }

export interface RunnerCallbacks {
  onClose: () => void
  onArmed: (pendingId: string | null) => void
  onPhase: (next: NextPhase) => void
}

/** The form phase: params, typed phrase, submit. */
export class Runner {
  readonly el: HTMLFormElement
  private readonly spec: CommandSpec
  private readonly fixed: Preset
  private readonly preset: Preset | undefined
  private readonly cb: RunnerCallbacks
  private values: ParamValues
  private typed = ''
  private showErrors = false
  private readonly form: ParamsForm
  private readonly start: Action<[Parameters<typeof startJob>[0]], Awaited<ReturnType<typeof startJob>>>
  private readonly phraseSlot = h('div', { class: 'contents' })
  private readonly errorSlot = h('div', { class: 'contents' })
  private readonly submitBtn: HTMLButtonElement
  private phraseKey: string | null = null

  constructor(fullSpec: CommandSpec, preset: Preset | undefined, cb: RunnerCallbacks) {
    const { spec, fixed } = enforcePreset(fullSpec, preset)
    this.spec = spec
    this.fixed = fixed
    this.preset = preset
    this.cb = cb
    this.values = initialValues(spec.params, preset)
    const locked = spec.locked_reason !== null
    this.form = new ParamsForm({
      specs: spec.params,
      values: this.values,
      disabled: locked,
      onChange: (v) => {
        this.values = v
        this.refresh()
      },
    })
    this.start = new Action(startJob, () => {
      this.refresh()
    })
    const countdown = spec.friction?.countdown_seconds
    this.submitBtn = h('button', {
      type: 'submit',
      class: 'btn btn-primary',
      autofocus: spec.params.every((p) => p.type === 'bool') && !spec.friction,
    })
    this.el = h(
      'form',
      { class: 'stack', novalidate: true },
      h('p', { class: 'm0' }, spec.description),
      h(
        'div',
        { class: 'tags' },
        spec.privileged ? pill('neutral', 'Runs as root via the daemon') : null,
        pill('neutral', spec.mutating ? 'Changes state' : 'Read-only'),
        spec.cancellable ? pill('neutral', 'Cancellable') : null,
        countdown ? pill('warning', `${Math.round(countdown / 60)} min countdown`) : null,
      ),
      spec.locked_reason !== null ? notice('warning', 'Locked', spec.locked_reason) : null,
      this.form.nodes,
      this.phraseSlot,
      this.errorSlot,
      h(
        'div',
        { class: 'actions' },
        this.submitBtn,
        h('button', { type: 'button', class: 'btn btn-ghost', onclick: () => { cb.onClose() } }, 'Cancel'),
      ),
    )
    this.el.addEventListener('submit', (e) => {
      e.preventDefault()
      void this.submit()
    })
    this.refreshGames()
  }

  refreshGames(): void {
    this.form.refresh(this.lookup().games, this.showErrors)
    this.refresh()
  }

  private lookup() {
    return gameLookup(q.dataset.state.data, q.installed.state.data, q.status.state.data)
  }

  private params(): Preset {
    return { ...this.fixed, ...toParams(this.spec.params, this.values) }
  }

  private phrase() {
    return this.spec.friction ? fillPhrase(this.spec.friction.phrase_template, this.params(), this.lookup().ctx) : null
  }

  private canSubmit(): boolean {
    const games = this.lookup().games
    const errors = this.spec.params.map((p) => paramError(p, this.values[p.name], games)).filter(Boolean)
    const phrase = this.phrase()
    return (
      this.spec.locked_reason === null &&
      errors.length === 0 &&
      (!phrase || (phrase.missing.length === 0 && phraseMatches(phrase.text, this.typed)))
    )
  }

  private refresh(): void {
    const phrase = this.phrase()
    const locked = this.spec.locked_reason !== null
    // The phrase field is rebuilt only when its sentence changes.
    const key = phrase ? `${phrase.missing.join(',')}|${phrase.text}` : null
    if (key !== this.phraseKey) {
      this.phraseKey = key
      if (phrase && phrase.missing.length > 0) {
        this.phraseSlot.replaceChildren(notice('info', null, `Fill in the fields above to see the exact phrase (${phrase.missing.join(', ')}).`))
      } else if (phrase && !locked) {
        this.typed = ''
        const field = new PhraseField({
          phrase: phrase.text,
          autofocus: this.spec.params.length === 0,
          onChange: (v) => {
            this.typed = v
            this.refresh()
          },
        })
        this.phraseSlot.replaceChildren(field.el)
      } else {
        this.phraseSlot.replaceChildren()
      }
    }
    const err = this.start.error
    const failure = err instanceof ApiFailure ? err : null
    const fallback = FALLBACK[this.spec.name]
    this.errorSlot.replaceChildren(
      ...(err
        ? [
            errorNotice(
              err,
              failure?.code === 'daemon_unreachable' && fallback
                ? [h('p', { class: 'm0' }, 'Run it from a terminal instead:'), commandLine(fallback)]
                : null,
            ),
          ]
        : []),
    )
    const countdown = this.spec.friction?.countdown_seconds
    this.submitBtn.className = phrase ? 'btn btn-danger' : 'btn btn-primary'
    this.submitBtn.disabled = !this.canSubmit() || this.start.pending
    this.submitBtn.textContent = this.start.pending ? 'Starting…' : countdown ? 'Arm countdown' : `Run ${this.spec.name}`
  }

  private async submit(): Promise<void> {
    this.showErrors = true
    this.form.refresh(this.lookup().games, true)
    if (!this.canSubmit()) return
    const phrase = this.phrase()
    // Every friction command sends its phrase here; a countdown one
    // (gaming-reset) needs it to arm and is asked again at commit.
    const out = await this.start.run({ command: this.spec.name, params: this.params(), ...(phrase ? { confirm_phrase: this.typed } : {}) })
    if (!out.ok) return
    q.jobs.invalidate()
    const started = out.value
    if (started.kind === 'job') {
      this.cb.onArmed(null)
      this.cb.onPhase({ k: 'job', id: started.job.id })
      return
    }
    this.cb.onArmed(started.pending.id)
    const countdown: PendingCountdown = new PendingCountdown(started.pending, {
      onCommitted: (job) => {
        this.cb.onArmed(null)
        this.cb.onPhase({ k: 'job', id: job.id })
      },
      onCancel: () => {
        this.cb.onArmed(null)
        this.cb.onClose()
      },
      onRearm: () => {
        this.cb.onArmed(null)
        this.cb.onPhase({ k: 'form', runner: new Runner(this.spec, this.preset, this.cb) })
      },
    })
    this.cb.onPhase({ k: 'pending', countdown })
  }
}
