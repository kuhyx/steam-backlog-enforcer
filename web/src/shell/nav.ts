import type { SectionPath } from '../commands/catalog'

export interface NavItem {
  to: SectionPath | '/jobs'
  /** Spoken only (aria-label); the sidebar paints `icon`. */
  label: string
  blurb: string
  icon: string
  /** Alt+<key> accelerator, shown in the sidebar as the bare digit. */
  key: string
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', blurb: 'Status, budget and quick actions', icon: '🏠', key: '1' },
  { to: '/backlog', label: 'Backlog', blurb: 'Planner, stats and the full game list', icon: '📚', key: '2' },
  { to: '/picks', label: 'Picks', blurb: 'Check, done, pick, scan, manual picks', icon: '🎯', key: '3' },
  { to: '/gaming', label: 'Gaming', blurb: 'Daily budget, reset, block, unblock', icon: '🎮', key: '4' },
  { to: '/library', label: 'Library', blurb: 'All your games, installed, install, uninstall, hide', icon: '🗂️', key: '5' },
  { to: '/store', label: 'Store', blurb: 'Unblock, buy DLC, exceptions', icon: '🛒', key: '6' },
  { to: '/jobs', label: 'Jobs', blurb: 'Running and past jobs', icon: '⚙️', key: '7' },
  { to: '/system', label: 'System', blurb: 'Daemon, server, backups, reset, setup', icon: '🖥️', key: '8' },
]
