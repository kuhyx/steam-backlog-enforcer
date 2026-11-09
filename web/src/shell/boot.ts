// Page-wide behaviour every page shares (was AppShell.tsx): section keys,
// the palette shortcut, the first-run redirect to Setup, refetching after a
// job ends, and reloading when a newer build is deployed.

import { q, refreshAfterJob } from '../api/queries'
import { go } from '../commands/palette'
import { hub } from '../jobs/hub'
import { runner } from '../lib/runner'
import { NAV } from './nav'

/** Alt+1…8 jumps between sections; Ctrl/Cmd+K toggles the palette. */
export function onShellKey(e: KeyboardEvent, palette: { toggle: () => void } | null): void {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    // A modal runner keeps focus; the palette waits until it closes.
    if (!document.querySelector('dialog[open].dialog-wide')) palette?.toggle()
    return
  }
  if (!e.altKey || e.ctrlKey || e.metaKey) return
  const item = NAV.find((n) => n.key === e.key)
  if (!item || document.querySelector('dialog[open]')) return
  e.preventDefault()
  go(item.to)
}

/** First run: every page but Setup sends an unconfigured install there. */
export function watchSetup(path: string): () => void {
  if (path.replace(/\/$/, '') === '/setup') return () => undefined
  return q.setup.subscribe((s) => {
    if (s.data && !s.data.configured) window.location.replace('/setup/')
  })
}

export const BUILD_META = 'sbe-build'
export const BUILD_POLL_MS = 30_000

/** The build stamp in an HTML document, or null. */
export function buildOf(html: string): string | null {
  return /<meta name="sbe-build" content="([^"]*)"/.exec(html)?.[1] ?? null
}

/**
 * Reload when the served page carries a different build stamp than this
 * one, so an open tab never keeps running a replaced bundle.
 */
export async function checkBuild(current: string): Promise<boolean> {
  try {
    const resp = await fetch(window.location.pathname, { cache: 'no-store' })
    const served = resp.ok ? buildOf(await resp.text()) : null
    if (served && served !== current) {
      window.location.reload()
      return true
    }
  } catch {
    // Server down: the health badge says so; try again next round.
  }
  return false
}

export function boot(): void {
  hub.onTerminal = refreshAfterJob
  const palette = document.querySelector<HTMLElement & { toggle: () => void }>('command-palette')
  window.addEventListener('keydown', (e) => {
    onShellKey(e, palette)
  })
  document.querySelector('[data-open-palette]')?.addEventListener('click', () => {
    runner.openPalette()
  })
  watchSetup(window.location.pathname)
  const build = document.querySelector<HTMLMetaElement>(`meta[name="${BUILD_META}"]`)?.content
  if (build) setInterval(() => void checkBuild(build), BUILD_POLL_MS)
}
