// `<command-button name="…" [preset='{"app_id":1}'] [label] [tone]>` and
// `<command-card …>` (was CommandCard.tsx): a catalog command as a button or
// a card with its server description and lock reason. A locked button stays
// focusable (aria-disabled), so a keyboard user can still reach it and read
// why. Non-job commands (views) link to the page that shows them.

import type { CommandName } from '../api/contract'
import { q } from '../api/queries'
import { define, h, jsonAttr } from '../lib/dom'
import { LiveElement } from '../lib/element'
import { pageHref, runner, type Preset } from '../lib/runner'
import { pill } from '../ui/build'
import { COMMAND_HOME, commandLabel, findCommand } from './catalog'

export interface ButtonProps {
  name: CommandName
  preset?: Preset
  label?: string
  tone?: string
}

function props(el: Element): ButtonProps {
  const preset = jsonAttr<Preset | undefined>(el, 'preset', undefined)
  const label = el.getAttribute('label')
  return {
    name: (el.getAttribute('name') ?? 'status') as CommandName,
    ...(preset ? { preset } : {}),
    ...(label ? { label } : {}),
    tone: el.getAttribute('tone') ?? 'ghost',
  }
}

/** The button for one command, from the current catalog. */
export function commandButton({ name, preset, label, tone = 'ghost' }: ButtonProps): HTMLElement {
  const spec = findCommand(q.commands.state.data, name)
  const locked = spec?.locked_reason ?? null
  const text = label ?? (spec?.kind === 'job' ? `Run ${name}` : `Open ${commandLabel(name)}`)
  if (spec && spec.kind !== 'job') return h('a', { href: pageHref(COMMAND_HOME[name]), class: `btn btn-${tone}` }, text)
  return h(
    'button',
    {
      type: 'button',
      class: `btn btn-${tone}`,
      'aria-disabled': String(locked !== null || !spec),
      title: locked,
      onclick: () => {
        if (spec && !locked) runner.run(name, preset)
      },
    },
    text,
  )
}

export class CommandButtonElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.commands)
  }

  protected update(): void {
    this.replaceChildren(commandButton(props(this)))
  }
}

export class CommandCardElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.commands)
  }

  protected update(): void {
    const p = props(this)
    const spec = findCommand(q.commands.state.data, p.name)
    const locked = spec?.locked_reason ?? null
    this.replaceChildren(
      h(
        'article',
        { class: locked ? 'cmd-card locked' : 'cmd-card' },
        h(
          'h3',
          { class: 'cmd-name' },
          commandLabel(p.name),
          spec?.privileged ? pill('neutral', 'root') : null,
          spec?.friction?.countdown_seconds ? pill('warning', 'countdown') : null,
        ),
        h('p', { class: 'cmd-desc' }, locked ?? spec?.description ?? '…'),
        commandButton(p),
      ),
    )
  }
}

define('command-button', CommandButtonElement)
define('command-card', CommandCardElement)
