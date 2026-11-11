// `<job-indicator>`: a top-bar chip for each running job (at most two), live
// from its SSE stream, linking to the job page. Present on every page.

import type { Job } from '../api/jobContract'
import { isActive, q } from '../api/queries'
import { COMMAND_ICON, commandLabel } from '../commands/catalog'
import { hub } from '../jobs/hub'
import { progressBar } from '../jobs/progress'
import { define, h } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { jobHref } from '../lib/runner'
import { glyph } from '../ui/build'

export function jobChip(job: Job): HTMLAnchorElement {
  const live = hub.get(job.id)
  const state = live.state ?? job.state
  const p = live.progress ?? job.progress
  const fraction = p?.total ? p.step / p.total : null
  const waiting = state === 'waiting_input'
  const label = commandLabel(job.command)
  return h(
    'a',
    {
      href: jobHref(job.id),
      class: waiting ? 'jobchip jobchip-wait' : 'jobchip',
      'aria-label': `${label}: ${waiting ? 'needs your input' : (p?.label ?? 'running')}`,
    },
    // Textgate: the command's glyph is painted; its name and "needs input" are spoken (aria-label above).
    h(
      'span',
      { class: 'jobchip-label' },
      glyph(COMMAND_ICON[job.command], label),
      h('span', { class: 'jobchip-sub' }, waiting ? glyph('✋', 'needs input') : p?.total ? `${p.step}/${p.total}` : '…'),
    ),
    progressBar(fraction, label, waiting ? 'warning' : 'accent', true),
  )
}

export class JobIndicatorElement extends LiveElement {
  private watched = new Map<string, () => void>()

  protected override setup(): void {
    this.watch(q.jobs)
    this.onCleanup(hub.subscribe(() => {
      this.update()
    }))
    this.onCleanup(() => {
      for (const unwatch of this.watched.values()) unwatch()
      this.watched.clear()
    })
  }

  protected update(): void {
    const active = (q.jobs.state.data ?? []).filter(isActive).slice(0, 2)
    const ids = new Set(active.map((j) => j.id))
    // Delete before unwatching: unwatch emits, which re-enters update().
    for (const [id, unwatch] of [...this.watched]) {
      if (!ids.has(id)) {
        this.watched.delete(id)
        unwatch()
      }
    }
    for (const j of active) if (!this.watched.has(j.id)) this.watched.set(j.id, hub.watch(j.id))
    this.replaceChildren(
      ...(active.length
        ? [h('div', { class: 'jobchips', 'aria-live': 'polite', 'aria-label': 'Running jobs' }, active.map(jobChip))]
        : []),
    )
  }
}

define('job-indicator', JobIndicatorElement)
