import type { SectionPath } from '../commands/catalog'
import type { IconId } from '../icons/registry'

export interface NavItem {
  to: SectionPath | '/jobs'
  /** Spoken (aria-label); the sidebar paints `icon` and the user's word for it. */
  label: string
  blurb: string
  icon: IconId
  /** Alt+<key> accelerator, shown in the sidebar as the bare digit. */
  key: string
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', blurb: 'Status, budget and quick actions', icon: 'nav.dashboard', key: '1' },
  { to: '/backlog', label: 'Backlog', blurb: 'Planner, stats and the full game list', icon: 'nav.backlog', key: '2' },
  { to: '/picks', label: 'Picks', blurb: 'Check, done, pick, scan, manual picks', icon: 'nav.picks', key: '3' },
  { to: '/gaming', label: 'Gaming', blurb: 'Daily budget, reset, block, unblock', icon: 'nav.gaming', key: '4' },
  { to: '/library', label: 'Library', blurb: 'All your games, installed, install, uninstall, hide', icon: 'nav.library', key: '5' },
  { to: '/store', label: 'Store', blurb: 'Unblock, buy DLC, exceptions', icon: 'nav.store', key: '6' },
  { to: '/jobs', label: 'Jobs', blurb: 'Running and past jobs', icon: 'nav.jobs', key: '7' },
  { to: '/system', label: 'System', blurb: 'Daemon, server, backups, reset, setup', icon: 'nav.system', key: '8' },
]

/** Pages reached from the palette only: no sidebar slot, no Alt key. */
export interface PalettePage {
  to: string
  label: string
  blurb: string
  icon: IconId
}

export const PALETTE_PAGES: PalettePage[] = [
  { to: '/words', label: 'Icon words', blurb: 'Pick the word shown next to each icon', icon: 'words.page' },
]
