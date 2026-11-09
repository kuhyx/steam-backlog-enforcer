// `<runner-dialog>`: the one generic job runner (was RunnerDialog.tsx +
// RunnerProvider.tsx). Opens on runner.run(); phases form → (countdown) →
// live job. An armed countdown dies with the dialog: close, Escape and
// leaving the page all drop it server-side.

import { api } from '../api/client'
import { q } from '../api/queries'
import { define, h, hx } from '../lib/dom'
import { runner, jobHref, type RunRequest } from '../lib/runner'
import { errorNotice, loading, notice } from '../ui/build'
import { Modal } from '../ui/dialog'
import { commandLabel, findCommand } from './catalog'
import type { PendingCountdown } from './pendingCountdown'
import { Runner, type NextPhase } from './runnerForm'

type Phase = { k: 'loading' } | { k: 'form'; runner: Runner } | { k: 'pending'; countdown: PendingCountdown } | { k: 'job'; id: string }

export class RunnerDialogElement extends HTMLElement {
  private modal = new Modal({ title: '', wide: true, onClose: () => { this.close() } })
  private request: RunRequest | null = null
  private phase: Phase = { k: 'loading' }
  private armed: string | null = null
  private unsubs: (() => void)[] = []
  private readonly onPageHide = () => {
    if (this.armed) void api.dropPending(this.armed, true).catch(() => undefined)
  }

  connectedCallback(): void {
    this.append(this.modal.el)
    this.unsubs.push(runner.onRun((req) => {
      this.open(req)
    }))
    window.addEventListener('pagehide', this.onPageHide)
  }

  disconnectedCallback(): void {
    this.close()
    for (const u of this.unsubs.splice(0)) u()
    window.removeEventListener('pagehide', this.onPageHide)
  }

  open(req: RunRequest): void {
    this.close()
    this.request = req
    this.modal.setTitle(commandLabel(req.name))
    // The catalog is polled; the form is built once from the first answer.
    this.unsubs.push(q.commands.subscribe(() => {
      this.render()
    }))
    for (const query of [q.dataset, q.installed, q.status]) {
      this.unsubs.push(query.subscribe(() => {
        if (this.phase.k === 'form') this.phase.runner.refreshGames()
      }))
    }
    this.phase = { k: 'loading' }
    this.render()
    this.modal.show()
  }

  close(): void {
    if (!this.request) return
    if (this.armed) void api.dropPending(this.armed).catch(() => undefined)
    this.armed = null
    if (this.phase.k === 'pending') this.phase.countdown.dispose()
    this.phase = { k: 'loading' }
    this.request = null
    // Keep the runner.onRun subscription (index 0); drop the per-open ones.
    for (const u of this.unsubs.splice(1)) u()
    this.modal.render()
    this.modal.hide()
  }

  private render(): void {
    const req = this.request
    if (!req) return
    if (this.phase.k !== 'loading') return
    const { data: commands, error } = q.commands.state
    const spec = findCommand(commands, req.name)
    if (spec) {
      const run = new Runner(spec, req.preset, {
        onClose: () => {
          this.close()
        },
        onArmed: (id) => {
          this.armed = id
        },
        onPhase: (next) => {
          this.setPhase(next)
        },
      })
      this.phase = { k: 'form', runner: run }
      this.modal.render(run.el)
      this.modal.focusFirst()
      return
    }
    if (error) this.modal.render(errorNotice(error))
    else if (commands) this.modal.render(notice('danger', 'Not in the server catalog', `The server does not offer "${req.name}".`))
    else this.modal.render(loading('commands'))
  }

  private setPhase(next: NextPhase): void {
    this.phase = next
    if (next.k === 'pending') {
      this.modal.render(next.countdown.el)
    } else if (next.k === 'job') {
      this.modal.render(
        h(
          'div',
          { class: 'stack' },
          hx('job-progress', { 'job-id': next.id }),
          h(
            'div',
            { class: 'actions' },
            h('button', { type: 'button', class: 'btn btn-ghost', onclick: () => { this.close() } }, 'Close (job keeps running)'),
            h('a', { href: jobHref(next.id), class: 'btn btn-ghost' }, 'Open in Jobs'),
          ),
        ),
      )
    } else {
      this.modal.render(next.runner.el)
    }
    this.modal.focusFirst()
  }
}


define('runner-dialog', RunnerDialogElement)
