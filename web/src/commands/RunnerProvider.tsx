import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { CommandName } from '../api/contract'
import { CommandPalette } from './CommandPalette'
import { RunnerContext } from './runnerContext'
import { RunnerDialog } from './RunnerDialog'

interface Open {
  name: CommandName
  preset?: Record<string, number | string>
  /** Changes per open so re-running the same command starts a fresh form. */
  nonce: number
}

/** Owns the one runner dialog and the command palette (Ctrl/Cmd+K). */
export function RunnerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Open | null>(null)
  const [palette, setPalette] = useState(false)

  const run = useCallback((name: CommandName, preset?: Record<string, number | string>) => {
    setPalette(false)
    setOpen({ name, preset, nonce: Date.now() })
  }, [])
  const openPalette = useCallback(() => setPalette(true), [])
  const close = useCallback(() => setOpen(null), [])
  const api = useMemo(() => ({ run, openPalette }), [run, openPalette])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        // A modal runner keeps focus; the palette waits until it closes.
        if (!document.querySelector('dialog[open].dialog-wide')) setPalette((p) => !p)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <RunnerContext.Provider value={api}>
      {children}
      {palette && <CommandPalette onClose={() => setPalette(false)} onRun={run} />}
      {open && <RunnerDialog key={open.nonce} name={open.name} preset={open.preset} onClose={close} />}
    </RunnerContext.Provider>
  )
}
