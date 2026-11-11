import { describe, expect, it } from 'vitest'
import { applyFilters } from '../../estimate'
import { makeDataset, makeFilters, makeGame, makeState } from '../../test/factories'
import type { EstimateBasis } from '../../types'
import { timelineChart, timelinePoints, timelineSvg } from './timeline'

const NOW = new Date(2026, 0, 1)

function chart(count: number, basis: EstimateBasis = 'leisure', pace = 0) {
  const games = Array.from({ length: count }, (_, i) => makeGame({ app_id: i + 1, name: `G${i}`, leisure_hours: 10 + i }))
  const filters = makeFilters({ basis })
  return timelineChart(applyFilters(makeDataset(games), filters), filters, makeState({ pace_games_per_day: pace }), NOW)
}

describe('timelinePoints', () => {
  it('accumulates hours shortest first at the daily rate', () => {
    const games = [makeGame({ app_id: 1, leisure_hours: 8 }), makeGame({ app_id: 2, leisure_hours: 4 })]
    const filters = makeFilters({ dailyHours: 2 })
    expect(timelinePoints(applyFilters(makeDataset(games), filters), filters, makeState())).toEqual([
      { day: 2, games: 1 },
      { day: 6, games: 2 },
    ])
  })

  it('spaces games by the pace for the pace basis, or gives up without one', () => {
    const filters = makeFilters({ basis: 'pace' })
    const result = applyFilters(makeDataset([makeGame({ app_id: 1 }), makeGame({ app_id: 2 })]), filters)
    expect(timelinePoints(result, filters, makeState({ pace_games_per_day: 0.5 }))).toEqual([
      { day: 2, games: 1 },
      { day: 4, games: 2 },
    ])
    expect(timelinePoints(result, filters, makeState())).toEqual([])
  })
})

describe('timelineChart', () => {
  it('shows a fallback message with fewer than two games', () => {
    const box = chart(1)
    expect(box.textContent).toContain('Not enough games in scope to draw a timeline.')
    expect(box.querySelector('.empty-icon')).not.toBeNull()
    expect(box.querySelector('.sr-only')?.textContent).toBe('Not enough games in scope to draw a timeline.')
    expect(box.querySelector('svg')).toBeNull()
  })

  it('draws an SVG line for the hours basis', () => {
    const box = chart(3, 'leisure')
    expect(box.querySelector('svg.chart-svg')).not.toBeNull()
    expect(box.querySelector('path.line')?.getAttribute('d')).toMatch(/^M[\d.]+ [\d.]+ L/)
    expect(box.querySelector('path.area')?.getAttribute('d')).toMatch(/ Z$/)
  })

  it('labels the y axis in games and the x axis in dates from now', () => {
    const box = chart(4, 'leisure')
    const labels = [...box.querySelectorAll('text')].map((t) => t.textContent)
    expect(labels.slice(0, 5)).toEqual(['0', '1', '2', '3', '4'])
    expect(labels[5]).toBe('2026-01-01')
    expect(labels).toHaveLength(10)
  })

  it('draws an SVG line for the pace basis when pace is known', () => {
    expect(chart(3, 'pace', 0.5).querySelector('svg.chart-svg')).not.toBeNull()
  })

  it('shows the fallback message for the pace basis with no pace', () => {
    expect(chart(3, 'pace', 0).textContent).toMatch(/Not enough games/)
  })

  it('falls back to a one-day span when the last point is day 0', () => {
    const svg = timelineSvg([{ day: -1, games: 1 }, { day: 0, games: 2 }], NOW)
    expect(svg.querySelector('path.line')?.getAttribute('d')).not.toMatch(/NaN|Infinity/)
  })

  it('survives an empty series', () => {
    expect(timelineSvg([], NOW).querySelector('path.line')?.getAttribute('d')).toBe('')
  })

  it('defaults the dates to today', () => {
    const svg = timelineSvg([{ day: 0, games: 1 }, { day: 1, games: 2 }])
    expect(svg.querySelectorAll('text.axis-label.mid')).toHaveLength(5)
    expect(chart(2).querySelector('svg')).not.toBeNull()
  })
})
