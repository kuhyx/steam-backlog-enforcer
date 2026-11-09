// The planner's "games finished by day N" chart (was TimelineChart.tsx) as a
// pure SVG element builder: points from the estimate, then one <svg>.

import type { EstimateResult } from '../../estimate'
import { isoDate } from '../../format'
import type { Filters, WebStateInfo } from '../../types'

const W = 820
const H = 320
const PAD = { top: 16, right: 20, bottom: 36, left: 48 }
const NS = 'http://www.w3.org/2000/svg'

export interface TimelinePoint {
  day: number
  games: number
}

/** The cumulative curve for the basis, shortest games first; [] when pace is unknown. */
export function timelinePoints(result: EstimateResult, filters: Filters, state: WebStateInfo): TimelinePoint[] {
  const rows = [...result.included].sort((a, b) => a.lengthHours - b.lengthHours)
  if (filters.basis === 'pace') {
    const pace = state.pace_games_per_day
    if (pace <= 0) return []
    return rows.map((_, i) => ({ day: (i + 1) / pace, games: i + 1 }))
  }
  let cum = 0
  return rows.map((r, i) => {
    cum += r.lengthHours
    return { day: cum / filters.dailyHours, games: i + 1 }
  })
}

function svg(tag: string, attrs: Record<string, string | number>, text?: string): SVGElement {
  const el = document.createElementNS(NS, tag)
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v))
  if (text !== undefined) el.textContent = text
  return el
}

function dayToDate(day: number, now: Date): string {
  const d = new Date(now)
  d.setDate(d.getDate() + Math.round(day))
  return isoDate(d)
}

/** The chart for at least two points; dates count from `now`. */
export function timelineSvg(pts: readonly TimelinePoint[], now: Date = new Date()): SVGElement {
  const maxDay = (pts.at(-1)?.day ?? 0) || 1
  const maxGames = pts.length
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const sx = (day: number) => PAD.left + (day / maxDay) * plotW
  const sy = (games: number) => PAD.top + plotH - (games / maxGames) * plotH

  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(p.day).toFixed(1)} ${sy(p.games).toFixed(1)}`).join(' ')
  const area = `${path} L${sx(maxDay).toFixed(1)} ${sy(0).toFixed(1)} L${sx(0).toFixed(1)} ${sy(0).toFixed(1)} Z`
  const fractions = [0, 0.25, 0.5, 0.75, 1]

  const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart-svg', role: 'img', 'aria-label': 'Completion timeline' })
  for (const g of fractions.map((f) => Math.round(f * maxGames))) {
    const group = svg('g', {})
    group.append(
      svg('line', { x1: PAD.left, y1: sy(g), x2: W - PAD.right, y2: sy(g), class: 'grid' }),
      svg('text', { x: PAD.left - 8, y: sy(g) + 4, class: 'axis-label end' }, String(g)),
    )
    root.append(group)
  }
  for (const d of fractions.map((f) => f * maxDay)) {
    root.append(svg('text', { x: sx(d), y: H - 12, class: 'axis-label mid' }, dayToDate(d, now)))
  }
  root.append(svg('path', { d: area, class: 'area' }), svg('path', { d: path, class: 'line' }))
  return root
}

/** The whole `.chart` box: title, SVG (or why there is none) and caption. */
export function timelineChart(
  result: EstimateResult,
  filters: Filters,
  state: WebStateInfo,
  now: Date = new Date(),
): HTMLDivElement {
  const pts = timelinePoints(result, filters, state)
  const box = document.createElement('div')
  box.className = 'chart'
  const title = document.createElement('h2')
  const hint = document.createElement('p')
  hint.className = 'hint'
  if (pts.length < 2) {
    title.textContent = 'Completion timeline'
    hint.textContent = 'Not enough games in scope to draw a timeline.'
    box.append(title, hint)
    return box
  }
  title.textContent = `Completion timeline · ${filters.basis}`
  hint.textContent = 'Cumulative games finished over time (shortest games first).'
  box.append(title, timelineSvg(pts, now), hint)
  return box
}
