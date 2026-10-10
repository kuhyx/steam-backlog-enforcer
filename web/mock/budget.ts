// `/api/budget` fixture: today's usage ticks up in real time so the budget
// cards visibly move while the mock runs.

import type { BudgetSnapshot } from '../src/types.ts'
import { hash } from './games.ts'

const LEGEND = [
  { key: 'app:1145360', label: 'Hades' },
  { key: 'app:367520', label: 'Hollow Knight' },
  { key: 'app:2379780', label: 'Balatro' },
  { key: 'launcher:steam', label: 'Steam (launcher)' },
  { key: 'other', label: 'Other' },
]

const started = Date.now()
let resetAt: number | null = null

export function resetToday(): void {
  resetAt = Date.now()
}

export function budget(demo: boolean): BudgetSnapshot {
  const budgetSeconds = demo ? 60 : 3 * 3600
  const base = demo ? 20 : 2 * 3600 + 10 * 60
  const since = resetAt ?? started
  const used = Math.min(budgetSeconds, (resetAt === null ? base : 0) + Math.floor((Date.now() - since) / 1000))
  const remaining = budgetSeconds - used
  const today = new Date()
  const history = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(today.getTime() - (13 - i) * 86_400_000)
    const h = hash(i + 7)
    const segs = LEGEND.map((l, j) => ({ key: l.key, seconds: j === 0 ? 1800 + (h % 5400) : (h >>> (j * 3)) % 2400 }))
    return {
      day: d.toISOString().slice(0, 10),
      seconds: segs.reduce((a, s) => a + s.seconds, 0),
      segments: segs,
    }
  })
  const slices = [
    { key: 'app:1145360', label: 'Hades', seconds: Math.round(used * 0.82), fraction: 0.82 },
    { key: 'launcher:steam', label: 'Steam (launcher)', seconds: Math.round(used * 0.18), fraction: 0.18 },
  ]
  return {
    ok: true,
    readable: true,
    state_status: 'ok',
    error: null,
    today: {
      gaming_day: today.toISOString().slice(0, 10),
      day_starts_at: '06:00 local',
      seconds_used: used,
      budget_seconds: budgetSeconds,
      seconds_remaining: remaining,
      fraction_used: used / budgetSeconds,
      blocked: remaining <= 0,
      blocked_at: remaining <= 0 ? Math.floor(Date.now() / 1000) : 0,
      next_warning_seconds: remaining > 1800 ? 1800 : remaining > 600 ? 600 : null,
      warned_seconds: remaining <= 3600 ? [3600] : [],
      games: used > 0 ? slices : [],
    },
    session: {
      available: true,
      observed_at: new Date().toISOString(),
      state: remaining > 0 ? 'engaged' : 'blocked',
      game_name: 'Hades',
      billing_label: 'Hades',
      qualifying_count: 2,
      processes: [
        { pid: 48211, name: 'Hades.exe' },
        { pid: 48190, name: 'steam' },
      ],
    },
    history,
    legend: LEGEND,
    rules: {
      budget_seconds: budgetSeconds,
      enforcement: true,
      counts_launchers: true,
      warn_at: [3600, 1800, 600, 300],
      demo,
      masked_launchers: ['heroic', 'lutris'],
      carry_seconds: demo ? 0 : 1200,
    },
  }
}
