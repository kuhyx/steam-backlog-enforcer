import { fmtDuration } from '../format'
import type { BudgetHistoryDay } from '../types'

interface Props {
  days: BudgetHistoryDay[]
  budgetSeconds: number
}

const W = 820
const H = 220
const PAD = { top: 16, right: 20, bottom: 36, left: 56 }

export function BudgetHistoryChart({ days, budgetSeconds }: Props) {
  if (days.length === 0) {
    return (
      <div className="chart">
        <h2>Last 14 days</h2>
        <p className="hint">
          No budget history recorded yet — a bar appears for each gaming day from now on.
        </p>
      </div>
    )
  }

  // Scaled against the budget rather than the tallest bar, so a single day
  // reads as "most of the allowance" instead of a lone full-height bar that
  // means nothing on its own.
  const maxSeconds =
    Math.max(budgetSeconds, ...days.map((d) => d.seconds)) || 1
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const sy = (seconds: number) => PAD.top + plotH - (seconds / maxSeconds) * plotH
  const slot = plotW / days.length
  const barW = slot * 0.7

  const yTicks = [0, 0.5, 1].map((f) => f * maxSeconds)

  return (
    <div className="chart">
      <h2>Last 14 days</h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img">
        {yTicks.map((s) => (
          <g key={`y${s}`}>
            <line x1={PAD.left} y1={sy(s)} x2={W - PAD.right} y2={sy(s)} className="grid" />
            <text x={PAD.left - 8} y={sy(s) + 4} className="axis-label end">
              {fmtDuration(s)}
            </text>
          </g>
        ))}
        <line
          x1={PAD.left}
          y1={sy(budgetSeconds)}
          x2={W - PAD.right}
          y2={sy(budgetSeconds)}
          className="budget-line"
        />
        {days.map((d, i) => (
          <rect
            key={d.day}
            x={PAD.left + i * slot + (slot - barW) / 2}
            y={sy(d.seconds)}
            width={barW}
            height={PAD.top + plotH - sy(d.seconds)}
            className={d.seconds >= budgetSeconds ? 'bar over' : 'bar'}
          >
            <title>{`${d.day}: ${fmtDuration(d.seconds)}`}</title>
          </rect>
        ))}
        {days.map((d, i) => (
          <text
            key={`x${d.day}`}
            x={PAD.left + i * slot + slot / 2}
            y={H - 12}
            className="axis-label mid"
          >
            {d.day.slice(5)}
          </text>
        ))}
      </svg>
      <p className="hint">
        Billed gaming time per day. The dashed line is the daily budget; today&apos;s bar
        can still move.
      </p>
    </div>
  )
}
