// Stacked 14-day budget bars as an SVG string (was BudgetHistoryChart.tsx).
// A string rather than DOM nodes: `h()` builds HTML-namespace elements, which
// an <svg> does not render, while innerHTML parses SVG markup correctly.

import { seriesClass } from '../../budgetSeries'
import { fmtDuration } from '../../format'
import type { BudgetHistoryDay, BudgetLegendEntry } from '../../types'

export const W = 820
export const H = 220
const PAD = { top: 16, right: 20, bottom: 36, left: 56 }

/** Escape text for SVG/HTML content and attribute values. */
export function esc(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Unrounded on purpose: stacked bands must abut exactly. */
const n = (v: number): string => String(v)

/** The chart for `days` (non-empty; the caller shows the empty state). */
export function budgetHistorySvg(days: readonly BudgetHistoryDay[], legend: readonly BudgetLegendEntry[], budgetSeconds: number): string {
  // Scaled against the budget rather than the tallest bar, so a single day
  // reads as "most of the allowance" instead of a lone full-height bar that
  // means nothing on its own.
  const maxSeconds = Math.max(budgetSeconds, ...days.map((d) => d.seconds)) || 1
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const sy = (seconds: number) => PAD.top + plotH - (seconds / maxSeconds) * plotH
  const slot = plotW / days.length
  const barW = slot * 0.7
  const labelFor = new Map(legend.map((e) => [e.key, e.label]))
  const indexFor = new Map(legend.map((e, i) => [e.key, i]))

  const yTicks = [0, 0.5, 1].map((f) => f * maxSeconds)
  const grid = yTicks.map(
    (s) =>
      `<g><line x1="${n(PAD.left)}" y1="${n(sy(s))}" x2="${n(W - PAD.right)}" y2="${n(sy(s))}" class="grid"/>` +
      `<text x="${n(PAD.left - 8)}" y="${n(sy(s) + 4)}" class="axis-label end">${esc(fmtDuration(s))}</text></g>`,
  )
  const budgetLine = `<line x1="${n(PAD.left)}" y1="${n(sy(budgetSeconds))}" x2="${n(W - PAD.right)}" y2="${n(sy(budgetSeconds))}" class="budget-line"/>`

  const bars = days.flatMap((d, i) => {
    // Bands stack upwards from the axis in legend order, so a game keeps the
    // same colour and the same relative position in every bar.
    let base = 0
    return d.segments.map((seg) => {
      const top = base + seg.seconds
      const y = sy(top)
      const height = sy(base) - y
      base = top
      const title = `${d.day} · ${labelFor.get(seg.key) ?? seg.key}: ${fmtDuration(seg.seconds)}`
      return (
        `<rect x="${n(PAD.left + i * slot + (slot - barW) / 2)}" y="${n(y)}" width="${n(barW)}" height="${n(height)}"` +
        ` class="${seriesClass(seg.key, indexFor.get(seg.key) ?? 0)}"><title>${esc(title)}</title></rect>`
      )
    })
  })

  const xLabels = days.map(
    (d, i) => `<text x="${n(PAD.left + i * slot + slot / 2)}" y="${n(H - 12)}" class="axis-label mid">${esc(d.day.slice(5))}</text>`,
  )

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" class="chart-svg" role="img" aria-label="Billed gaming time per day">` +
    [...grid, budgetLine, ...bars, ...xLabels].join('') +
    '</svg>'
  )
}
