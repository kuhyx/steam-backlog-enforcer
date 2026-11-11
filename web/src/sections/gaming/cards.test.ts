import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeBudgetRules, makeBudgetSession, makeBudgetToday } from '../../test/factories'
import { OTHER_KEY, UNATTRIBUTED_KEY } from '../../budgetSeries'
import { historyCard, liveCard, rulesCard, seriesLabel, todayCard, todayUnavailable } from './cards'

const show = (el: HTMLElement) => {
  document.body.replaceChildren(el)
}

describe('todayCard', () => {
  it('shows remaining time, usage and the next warning', () => {
    show(todayCard(makeBudgetToday(), [], 0))
    expect(screen.getByText('7h 0m')).toBeInTheDocument()
    expect(screen.getByText(/1h 0m of 8h 0m used · 13% · gaming day 2026-08-28 \(starts 06:00 local\)/)).toBeInTheDocument()
    expect(screen.getByText(/Next warning at 1h 0m remaining/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--ok')).not.toBeNull()
    expect(document.querySelector<HTMLElement>('.budget-meter-fill')?.style.width).toBe('12.5%')
  })

  it('turns the meter amber once a warning has fired', () => {
    show(todayCard(makeBudgetToday({ seconds_remaining: 900, warned_seconds: [3600, 1800] }), [], 0))
    expect(document.querySelector('.budget-meter--warn')).not.toBeNull()
  })

  it('says so when no warnings remain', () => {
    show(todayCard(makeBudgetToday({ next_warning_seconds: null, warned_seconds: [3600, 1800, 600, 300] }), [], 0))
    expect(screen.getByText(/No further warnings today/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--warn')).not.toBeNull()
  })

  const blockedToday = () =>
    makeBudgetToday({ blocked: true, blocked_at: 1, seconds_used: 28800, seconds_remaining: 0, fraction_used: 1, next_warning_seconds: null })

  it('shows the cutoff badge when blocked', () => {
    show(todayCard(blockedToday(), [], 2))
    expect(screen.getByText(/Cutoff engaged — launchers are masked/)).toBeInTheDocument()
    expect(document.querySelector('.budget-meter--blocked')).not.toBeNull()
  })

  it('does not claim a mask that is not in place', () => {
    show(todayCard(blockedToday(), [], 0))
    expect(screen.getByText(/Cutoff engaged — launchers are not currently masked/)).toBeInTheDocument()
  })

  it('colours games by legend position, else by their own row', () => {
    const games = [
      { key: 'app:1', label: 'One', seconds: 1800, fraction: 0.5 },
      { key: 'app:2', label: 'Two', seconds: 1800, fraction: 0.5 },
    ]
    show(todayCard(makeBudgetToday({ games }), [{ key: 'app:9', label: 'Nine' }, { key: 'app:2', label: 'Two' }], 0))
    const swatches = [...document.querySelectorAll('.budget-games .swatch')].map((s) => s.className)
    // app:1 is not in the legend → its row index 0 → cat-1; app:2 is legend entry 1 → cat-2.
    expect(swatches).toEqual(['swatch seg cat-1', 'swatch seg cat-2'])
    expect(screen.getByText('Today by game')).toBeInTheDocument()
    expect(screen.getAllByText('50%')).toHaveLength(2)
  })

  it('omits the per-game list when nothing billed', () => {
    show(todayCard(makeBudgetToday({ games: [] }), [], 0))
    expect(screen.queryByText('Today by game')).toBeNull()
  })
})

describe('todayUnavailable', () => {
  it('shows the backend reason, or a default', () => {
    show(todayUnavailable('Cannot read the budget state file.'))
    expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument()
    expect(screen.getByText('Cannot read the budget state file.')).toHaveClass('error')
    show(todayUnavailable(null))
    expect(screen.getByText('Budget state unavailable.')).toBeInTheDocument()
  })
})

describe('liveCard', () => {
  it('reports an engaged session with its game', () => {
    show(liveCard(makeBudgetSession()))
    expect(screen.getByText(/Billing — you are playing/).closest('.budget-verdict')).toHaveClass('budget-verdict--engaged')
    expect(screen.getByText(/Assigned game/)).toBeInTheDocument()
    // Engaged, so the credited game is described in the present tense.
    expect(screen.getByText(/Billing to/)).toBeInTheDocument()
    expect(screen.getAllByText('Hollow Knight')).toHaveLength(2)
    expect(screen.getByText(/3 qualifying processes/)).toBeInTheDocument()
    expect(screen.getByText('as of just now')).toBeInTheDocument()
  })

  it('falls back to the raw verdict when unrecognised', () => {
    show(liveCard(makeBudgetSession({ state: 'weird' })))
    expect(screen.getByText('weird')).toBeInTheDocument()
    expect(screen.getByText(/Last billed to/)).toBeInTheDocument()
  })

  it('omits the game line when nothing qualifies', () => {
    show(liveCard(makeBudgetSession({ state: 'not_applicable', qualifying_count: 0, processes: [] })))
    expect(screen.getByText(/no game running/)).toBeInTheDocument()
    expect(screen.queryByText(/qualifying processes/)).toBeNull()
  })

  it('handles a qualifying session with no assigned game name', () => {
    show(liveCard(makeBudgetSession({ game_name: '', billing_label: '' })))
    expect(screen.getByText(/3 qualifying processes/)).toBeInTheDocument()
    expect(screen.queryByText('Hollow Knight')).toBeNull()
    expect(screen.queryByText(/Assigned game/)).toBeNull()
  })

  it('says when no verdict has been logged', () => {
    show(liveCard(makeBudgetSession({ available: false })))
    expect(screen.getByText(/No verdict has been logged yet/)).toBeInTheDocument()
  })
})

describe('liveCard reading age', () => {
  const painted = () => document.querySelector('.hint:last-child [aria-hidden="true"]')?.textContent
  const spoken = () => document.querySelector('.hint:last-child .sr-only')?.textContent

  it('paints a clock and "<10s" for a fresh reading', () => {
    show(liveCard(makeBudgetSession()))
    expect(painted()).toBe('🕓 <10s')
    expect(spoken()).toBe('as of just now')
  })

  it('paints the age without "ago" for an older reading', () => {
    show(liveCard(makeBudgetSession({ observed_at: new Date(Date.now() - 125_000).toISOString() })))
    expect(painted()).toMatch(/^🕓 2m/)
    expect(spoken()).toMatch(/^as of 2m.* ago$/)
  })

  it('paints "?" when the reading time is unknown', () => {
    show(liveCard(makeBudgetSession({ observed_at: '' })))
    expect(painted()).toBe('🕓 ?')
    expect(spoken()).toBe('as of unknown')
  })
})

describe('seriesLabel', () => {
  const paintedOf = (el: HTMLElement) => el.querySelector('[aria-hidden="true"]')?.textContent
  const spokenOf = (el: HTMLElement) => el.querySelector('.sr-only')?.textContent

  it('paints a plus for the grouped remainder and speaks its label', () => {
    const el = seriesLabel(OTHER_KEY, 'Other games')
    expect(paintedOf(el)).toBe('➕')
    expect(spokenOf(el)).toBe('Other games')
  })

  it('paints a question mark for unattributed time', () => {
    const el = seriesLabel(UNATTRIBUTED_KEY, 'Unattributed')
    expect(paintedOf(el)).toBe('❔')
    expect(spokenOf(el)).toBe('Unattributed')
  })

  it('paints a rocket and the bare name for a launcher, speaking the full label', () => {
    const el = seriesLabel('launcher:steam', 'Steam (launcher)')
    expect(paintedOf(el)).toBe('🚀 Steam')
    expect(spokenOf(el)).toBe('Steam (launcher)')
  })

  it('paints a game name as plain text', () => {
    const el = seriesLabel('app:1', 'Titan Quest')
    expect(el.textContent).toBe('Titan Quest')
    expect(el.querySelector('.sr-only')).toBeNull()
  })
})

describe('historyCard', () => {
  const legend = [
    { key: 'app:475150', label: 'Titan Quest' },
    { key: 'proc:osu-lazer', label: 'osu!lazer' },
    { key: 'unattributed', label: 'Unattributed' },
  ]

  it('explains itself when nothing has been recorded', () => {
    show(historyCard([], [], 28800))
    expect(screen.getByText(/No budget history recorded yet/)).toBeInTheDocument()
    expect(document.querySelector('svg')).toBeNull()
  })

  it('draws the chart as real SVG with a legend', () => {
    show(historyCard([{ day: '2026-08-28', seconds: 14400, segments: [{ key: 'app:475150', seconds: 14400 }] }], legend, 28800))
    expect(screen.getByRole('heading', { name: 'Last 14 days' })).toBeInTheDocument()
    const svg = document.querySelector('.chart > svg.chart-svg')
    expect(svg?.namespaceURI).toBe('http://www.w3.org/2000/svg')
    expect(document.querySelector('rect.seg title')?.textContent).toContain('Titan Quest')
    expect(document.querySelectorAll('.chart-legend li')).toHaveLength(legend.length)
    expect(document.querySelector('.chart-legend li:last-child .swatch')).toHaveClass('unattributed')
    expect(screen.getByText(/The dashed line is the daily budget/)).toBeInTheDocument()
  })
})

describe('rulesCard', () => {
  it('lists the production policy', () => {
    show(rulesCard(makeBudgetRules()))
    expect(screen.getByText('8h 0m')).toBeInTheDocument()
    expect(screen.getByText('on')).toBeInTheDocument()
    expect(screen.getByText('yes')).toBeInTheDocument()
    expect(screen.getByText(/1h 0m, 30m, 10m, 5m remaining/)).toBeInTheDocument()
    expect(screen.queryByText(/demo/)).toBeNull()
    expect(screen.queryByText('Masked now')).toBeNull()
  })

  it('shows the demo mode and masked launchers when they apply', () => {
    show(rulesCard(makeBudgetRules({ enforcement: false, counts_launchers: false, demo: true, masked_launchers: ['/usr/bin/steam', 'lutris'] })))
    expect(screen.getByText(/demo \(short budget/)).toBeInTheDocument()
    expect(screen.getByText('/usr/bin/steam, lutris')).toBeInTheDocument()
    expect(screen.getByText('no')).toBeInTheDocument()
    expect(screen.getByText('off')).toBeInTheDocument()
  })
})
