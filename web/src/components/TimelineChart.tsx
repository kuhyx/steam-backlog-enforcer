import type { EstimateResult } from '../estimate'
import { isoDate } from '../format'
import type { Filters, WebStateInfo } from '../types'

interface Props {
  result: EstimateResult
  filters: Filters
  state: WebStateInfo
}

const W = 820
const H = 320
const PAD = { top: 16, right: 20, bottom: 36, left: 48 }

interface Point {
  day: number
  games: number
}

/** Build the cumulative "games finished by day N" curve for the basis. */
function buildPoints(props: Props): Point[] {
  const { result, filters, state } = props
  const rows = [...result.included].sort((a, b) => a.lengthHours - b.lengthHours)
  const pts: Point[] = []
  if (filters.basis === 'pace') {
    const pace = state.pace_games_per_day
    if (pace <= 0) return []
    rows.forEach((_, i) => pts.push({ day: (i + 1) / pace, games: i + 1 }))
    return pts
  }
  let cum = 0
  rows.forEach((r, i) => {
    cum += r.lengthHours
    pts.push({ day: cum / filters.dailyHours, games: i + 1 })
  })
  return pts
}

function dayToDate(day: number): string {
  const d = new Date()
  d.setDate(d.getDate() + Math.round(day))
  return isoDate(d)
}

export function TimelineChart(props: Props) {
  const pts = buildPoints(props)
  if (pts.length < 2) {
    return (
      <div className="chart">
        <h2>Completion timeline</h2>
        <p className="hint">Not enough games in scope to draw a timeline.</p>
      </div>
    )
  }

  const maxDay = pts[pts.length - 1].day || 1
  const maxGames = pts.length
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const sx = (day: number) => PAD.left + (day / maxDay) * plotW
  const sy = (games: number) => PAD.top + plotH - (games / maxGames) * plotH

  const path = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(p.day).toFixed(1)} ${sy(p.games).toFixed(1)}`)
    .join(' ')
  const area = `${path} L${sx(maxDay).toFixed(1)} ${sy(0).toFixed(1)} L${sx(0).toFixed(1)} ${sy(0).toFixed(1)} Z`

  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxDay)
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * maxGames))

  return (
    <div className="chart">
      <h2>Completion timeline · {props.filters.basis}</h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart-svg" role="img">
        {yTicks.map((g) => (
          <g key={`y${g}`}>
            <line
              x1={PAD.left}
              y1={sy(g)}
              x2={W - PAD.right}
              y2={sy(g)}
              className="grid"
            />
            <text x={PAD.left - 8} y={sy(g) + 4} className="axis-label end">
              {g}
            </text>
          </g>
        ))}
        {xTicks.map((d) => (
          <text key={`x${d}`} x={sx(d)} y={H - 12} className="axis-label mid">
            {dayToDate(d)}
          </text>
        ))}
        <path d={area} className="area" />
        <path d={path} className="line" />
      </svg>
      <p className="hint">
        Cumulative games finished over time (shortest games first).
      </p>
    </div>
  )
}
