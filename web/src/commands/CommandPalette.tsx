import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type KeyboardEvent } from 'react'
import type { CommandName } from '../api/contract'
import { q } from '../api/queries'
import { NAV } from '../shell/nav'
import { Dialog } from '../ui/Dialog'
import { ErrorNotice, Loading } from '../ui/Notice'
import { COMMAND_HOME, commandLabel, type SectionPath } from './catalog'

interface Entry {
  key: string
  title: string
  detail: string
  hint: string
  locked: string | null
  act: () => void
}

/**
 * Ctrl/Cmd+K: every command from `GET /api/commands`, plus the sections.
 * A combobox + listbox pair: arrows move, Enter runs, Escape closes, and the
 * active option is announced via aria-activedescendant.
 */
export function CommandPalette({ onClose, onRun }: { onClose: () => void; onRun: (n: CommandName) => void }) {
  const id = useId()
  const navigate = useNavigate()
  const { data: commands, error } = useQuery(q.commands)
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)

  const go = (to: SectionPath | '/jobs') => {
    onClose()
    void navigate({ to })
  }
  const entries: Entry[] = [
    ...(commands ?? []).map((c) => ({
      key: c.name,
      title: commandLabel(c.name),
      detail: c.description,
      hint: c.kind === 'job' ? (c.friction ? 'run · confirm' : 'run') : `open ${COMMAND_HOME[c.name]}`,
      locked: c.locked_reason,
      act: () => (c.kind === 'job' ? onRun(c.name) : go(COMMAND_HOME[c.name])),
    })),
    ...NAV.map((n) => ({ key: `nav:${n.to}`, title: `Go to ${n.label}`, detail: n.blurb, hint: 'navigate', locked: null, act: () => go(n.to) })),
  ]
  const needle = text.trim().toLowerCase()
  const shown = needle
    ? entries.filter((e) => `${e.key} ${e.title} ${e.detail}`.toLowerCase().includes(needle))
    : entries
  const current = Math.min(active, Math.max(0, shown.length - 1))

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    const last = shown.length - 1
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, current + 1),
      ArrowUp: Math.max(0, current - 1),
      PageDown: Math.min(last, current + 8),
      PageUp: Math.max(0, current - 8),
    }
    if (e.key in moves) {
      e.preventDefault()
      setActive(moves[e.key])
      document.getElementById(`${id}-${moves[e.key]}`)?.scrollIntoView({ block: 'nearest' })
    } else if (e.key === 'Enter' && shown[current]) {
      e.preventDefault()
      shown[current].act()
    }
  }

  return (
    <Dialog open title="Command palette" onClose={onClose}>
      <input
        className="input palette-input"
        role="combobox"
        aria-expanded="true"
        aria-controls={`${id}-list`}
        aria-activedescendant={shown[current] ? `${id}-${current}` : undefined}
        aria-label="Search commands"
        placeholder="Type a command or section…"
        value={text}
        autoFocus
        onChange={(e) => {
          setText(e.target.value)
          setActive(0)
        }}
        onKeyDown={onKey}
      />
      {error && <ErrorNotice error={error} />}
      {!commands && !error && <Loading what="commands" />}
      <ul id={`${id}-list`} role="listbox" className="palette-list" aria-label="Commands">
        {shown.map((e, i) => (
          <li
            key={e.key}
            id={`${id}-${i}`}
            role="option"
            aria-selected={i === current}
            className={i === current ? 'palette-item active' : 'palette-item'}
            onMouseMove={() => setActive(i)}
            onClick={e.act}
          >
            <span className="palette-title">
              {e.title}
              {e.locked && <span className="pill pill-warning">locked</span>}
            </span>
            <span className="palette-detail">{e.locked ?? e.detail}</span>
            <span className="palette-hint">{e.hint}</span>
          </li>
        ))}
        {shown.length === 0 && <li className="empty">No command matches “{text}”.</li>}
      </ul>
      <p className="field-help">↑↓ to move · Enter to run · Esc to close</p>
    </Dialog>
  )
}
