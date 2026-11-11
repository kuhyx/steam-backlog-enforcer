// `<backups-card>` (was screens/system/BackupsCard.tsx): state backups, the
// reset that makes them, and a typed-phrase restore that then shows the
// restore job live. The dialog lives outside the list, so the refetch a
// finished job triggers never tears it down mid-progress.

import { api } from '../../api/client'
import { explain } from '../../api/errors'
import type { StateBackup } from '../../api/contract'
import type { Job } from '../../api/jobContract'
import { q } from '../../api/queries'
import { phraseMatches } from '../../commands/catalog'
import '../../commands/commandButton'
import { PhraseField } from '../../commands/phraseField'
import '../../jobs/jobProgress'
import { Action } from '../../lib/action'
import { define, h, hx } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { card, empty, errorNotice, glyph, loading } from '../../ui/build'
import { Modal } from '../../ui/dialog'
import { bytes, dateTime } from '../../ui/format'

// Not in any CommandSpec (restore is not a CLI command), so the UI has to
// know it. Mirrors FRICTION["restore-backup"] in _friction.py.
export const restorePhrase = (id: string): string => `restore backup ${id}`

/** Why a backup was taken, as a glyph (reason words spoken only). */
const REASON_ICON: Record<string, string> = { 'before reset': '♻️', nightly: '🌙' }
const reasonGlyph = (reason: string): HTMLSpanElement => glyph(REASON_ICON[reason] ?? '🗄️', reason)

/** One restore: phrase form, then the job it started. */
export class RestoreDialog {
  readonly modal: Modal
  private readonly phrase: string
  private readonly field: PhraseField
  private readonly submit = h('button', { type: 'submit', class: 'btn btn-danger' })
  private readonly failure = h('div', { class: 'contents' })
  private readonly restore: Action<[], Job>

  constructor(backup: StateBackup, onClose: () => void) {
    this.phrase = restorePhrase(backup.id)
    this.modal = new Modal({ title: `Restore backup ${backup.id}`, wide: true, onClose })
    this.field = new PhraseField({
      phrase: this.phrase,
      autofocus: true,
      onChange: () => {
        this.sync()
      },
    })
    this.restore = new Action(
      () => api.restoreBackup(backup.id, this.field.value),
      () => {
        this.sync()
      },
    )
    const form = h(
      'form',
      {
        class: 'stack',
        onsubmit: (e: Event) => {
          e.preventDefault()
          if (this.matches() && !this.restore.pending) void this.run(onClose)
        },
      },
      // Painted: the backup's id, date and reason glyph; the sentence is spoken only.
      h(
        'p',
        { class: 'm0 row' },
        h('span', { class: 'sr-only' }, `Replaces the current state with the backup from ${dateTime(backup.created_at)} (${backup.reason}).`),
        h('span', { 'aria-hidden': 'true', class: 'mono' }, `🗄️ ${backup.id} · ${dateTime(backup.created_at)}`),
        h('span', { 'aria-hidden': 'true' }, REASON_ICON[backup.reason] ?? '🗄️'),
      ),
      this.field.el,
      this.failure,
      h(
        'div',
        { class: 'actions' },
        this.submit,
        h('button', { type: 'button', class: 'btn btn-ghost', onclick: onClose }, glyph('✖️', 'Cancel')),
      ),
    )
    this.modal.render(form)
    this.sync()
  }

  private matches(): boolean {
    return phraseMatches(this.phrase, this.field.value)
  }

  private sync(): void {
    this.submit.disabled = !this.matches() || this.restore.pending
    this.submit.replaceChildren(this.restore.pending ? glyph('⏳', 'Restoring…') : glyph('⏮️', 'Restore'))
    this.failure.replaceChildren(...(this.restore.error ? [errorNotice(this.restore.error)] : []))
  }

  private async run(onClose: () => void): Promise<void> {
    const out = await this.restore.run()
    if (!out.ok) return
    q.jobs.invalidate()
    this.modal.render(
      h(
        'div',
        { class: 'stack' },
        hx('job-progress', { 'job-id': out.value.id }),
        h('div', { class: 'actions' }, h('button', { type: 'button', class: 'btn btn-ghost', onclick: onClose }, glyph('✖️', 'Close'))),
      ),
    )
    this.modal.focusFirst()
  }
}

export class BackupsCardElement extends LiveElement {
  private readonly status = h('div', { class: 'contents' })
  private readonly list = h('ul', { class: 'rows' })
  private readonly root = card(
    'State backups',
    [h('p', { class: 'sr-only' }, 'Reset takes a timestamped backup first, so it can be undone here.'), this.status, this.list],
    { aside: hx('command-button', { name: 'reset', label: 'Reset all state…' }), icon: '🗄️' },
  )
  private dialog: RestoreDialog | null = null
  private shownKey = ''

  protected override setup(): void {
    this.shownKey = ''
    this.replaceChildren(this.root)
    this.watch(q.backups)
    this.onCleanup(() => {
      this.close()
    })
  }

  protected update(): void {
    const { data, error } = q.backups.state
    // Rebuild only on a real change, so a refetch leaves focus where it was.
    const key = JSON.stringify([data ?? null, error ? explain(error) : null])
    if (key === this.shownKey) return
    this.shownKey = key
    this.status.replaceChildren(
      ...(error ? [errorNotice(error)] : []),
      ...(!data && !error ? [loading('backups')] : []),
      ...(data?.length === 0 ? [empty('No backups yet.')] : []),
    )
    this.list.replaceChildren(
      ...(data ?? []).map((b) =>
        h(
          'li',
          { class: 'row' },
          h('span', { class: 'mono' }, b.id),
          h(
            'span',
            { class: 'muted grow', 'data-reason': b.reason },
            `${dateTime(b.created_at)} · `,
            reasonGlyph(b.reason),
            ` · ${bytes(b.size_bytes)}`,
          ),
          h(
            'button',
            {
              type: 'button',
              class: 'btn btn-ghost btn-small',
              onclick: () => {
                this.open(b)
              },
            },
            glyph('⏮️', 'Restore…'),
          ),
        ),
      ),
    )
  }

  open(backup: StateBackup): void {
    this.close()
    const dialog = new RestoreDialog(backup, () => {
      this.close()
    })
    this.dialog = dialog
    this.append(dialog.modal.el)
    dialog.modal.show()
  }

  close(): void {
    const dialog = this.dialog
    if (!dialog) return
    this.dialog = null
    dialog.modal.hide()
    dialog.modal.el.remove()
  }
}

define('backups-card', BackupsCardElement)
