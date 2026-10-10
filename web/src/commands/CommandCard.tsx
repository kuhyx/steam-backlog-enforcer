import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { CommandName } from '../api/contract'
import { q } from '../api/queries'
import { COMMAND_HOME, commandLabel, findCommand } from './catalog'
import { useRunner } from './runnerContext'

interface Props {
  name: CommandName
  preset?: Record<string, number | string>
  /** Override the button text (defaults to the command name). */
  label?: string
  tone?: 'primary' | 'ghost' | 'danger'
}

/**
 * A command as a card: name, server description, lock reason. The button
 * stays focusable while locked (aria-disabled), so a keyboard user can still
 * reach it and read why.
 */
export function CommandCard({ name, preset, label, tone }: Props) {
  const { data: commands } = useQuery(q.commands)
  const spec = findCommand(commands, name)
  const locked = spec?.locked_reason ?? null
  const btn = tone ?? 'ghost'
  return (
    <article className={locked ? 'cmd-card locked' : 'cmd-card'}>
      <h3 className="cmd-name">
        {commandLabel(name)}
        {spec?.privileged && <span className="pill pill-neutral">root</span>}
        {spec?.friction?.countdown_seconds ? <span className="pill pill-warning">countdown</span> : null}
      </h3>
      <p className="cmd-desc">{locked ?? spec?.description ?? '…'}</p>
      <CommandButton name={name} preset={preset} label={label} tone={btn} />
    </article>
  )
}

export function CommandButton({ name, preset, label, tone = 'ghost' }: Props) {
  const { run } = useRunner()
  const { data: commands } = useQuery(q.commands)
  const spec = findCommand(commands, name)
  const locked = spec?.locked_reason ?? null
  const text = label ?? (spec?.kind === 'job' ? `Run ${name}` : `Open ${commandLabel(name)}`)
  if (spec && spec.kind !== 'job') {
    return (
      <Link to={COMMAND_HOME[name]} className={`btn btn-${tone}`}>
        {text}
      </Link>
    )
  }
  return (
    <button
      type="button"
      className={`btn btn-${tone}`}
      aria-disabled={locked !== null || !spec}
      title={locked ?? undefined}
      onClick={() => {
        if (spec && !locked) run(name, preset)
      }}
    >
      {text}
    </button>
  )
}
