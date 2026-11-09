// Module-level replacement for RunnerProvider: any button anywhere asks for
// the runner or the palette here, and the one <runner-dialog> /
// <command-palette> in the shell listens.

import type { CommandName } from '../api/contract'

export type Preset = Record<string, number | string>

export interface RunRequest {
  name: CommandName
  preset?: Preset
}

const bus = new EventTarget()

export const runner = {
  /** Open the generic runner for a job command, optionally pre-filled. */
  run(name: CommandName, preset?: Preset): void {
    bus.dispatchEvent(new CustomEvent<RunRequest>('run', { detail: preset ? { name, preset } : { name } }))
  },
  openPalette(): void {
    bus.dispatchEvent(new Event('palette'))
  },
  onRun(fn: (req: RunRequest) => void): () => void {
    const listener = (e: Event) => {
      fn((e as CustomEvent<RunRequest>).detail)
    }
    bus.addEventListener('run', listener)
    return () => {
      bus.removeEventListener('run', listener)
    }
  },
  onPalette(fn: () => void): () => void {
    bus.addEventListener('palette', fn)
    return () => {
      bus.removeEventListener('palette', fn)
    }
  },
}

/** Where a section lives as a static page: `/library` → `/library/`. */
export function pageHref(to: string): string {
  return to === '/' ? '/' : `${to.replace(/\/$/, '')}/`
}

/** The job detail page (static output cannot prerender unknown ids). */
export function jobHref(id: string): string {
  return `/jobs/?id=${encodeURIComponent(id)}`
}
