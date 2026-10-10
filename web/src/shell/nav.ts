import type { SectionPath } from '../commands/catalog'

export interface NavItem {
  to: SectionPath | '/jobs'
  label: string
  blurb: string
  /** Alt+<key> accelerator, shown in the sidebar. */
  key: string
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', blurb: 'Status, budget and quick actions', key: '1' },
  { to: '/backlog', label: 'Backlog', blurb: 'Planner, stats and the full game list', key: '2' },
  { to: '/picks', label: 'Picks', blurb: 'Check, done, pick, scan, manual picks', key: '3' },
  { to: '/gaming', label: 'Gaming', blurb: 'Daily budget, reset, block, unblock', key: '4' },
  { to: '/library', label: 'Library', blurb: 'All your games, installed, install, uninstall, hide', key: '5' },
  { to: '/store', label: 'Store', blurb: 'Unblock, buy DLC, exceptions', key: '6' },
  { to: '/jobs', label: 'Jobs', blurb: 'Running and past jobs', key: '7' },
  { to: '/system', label: 'System', blurb: 'Daemon, server, backups, reset, setup', key: '8' },
]
