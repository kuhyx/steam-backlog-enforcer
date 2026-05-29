import { basisTotal, etaDays, paceDays } from '../estimate'
import type { EstimateResult } from '../estimate'
import { daysUntil, fmtEta, fmtHours } from '../format'
import type { EstimateBasis, Filters, WebStateInfo } from '../types'

interface Props {
  result: EstimateResult
  filters: Filters
  state: WebStateInfo
  presets: number[]
  defaultQualifying: number
}

interface CardData {
  basis: EstimateBasis
  title: string
  blurb: string
}

const CARDS: CardData[] = [
  { basis: 'rush', title: 'Rush', blurb: 'Typical fast completionist' },
  { basis: 'leisure', title: 'Leisure', blurb: 'Slow, comfortable 100%' },
  { basis: 'worst', title: 'Worst case', blurb: 'Max recorded time' },
  { basis: 'pace', title: 'At your pace', blurb: 'Based on games finished' },
]

function TargetBanner({ result, filters }: Props) {
  if (!filters.targetDate) return null
  const days = Math.max(1, daysUntil(filters.targetDate))
  let need: string
  if (filters.basis === 'pace') {
    const perDay = result.remainingGames / days
    need = `${perDay.toFixed(2)} games/day`
  } else {
    const total = basisTotal(result, filters.basis) as number
    need = `${(total / days).toFixed(1)} h/day`
  }
  return (
    <div className="target-banner">
      To finish <strong>{result.remainingGames}</strong> games by{' '}
      <strong>{filters.targetDate}</strong> ({days} days) on the{' '}
      <strong>{filters.basis}</strong> model, you need <strong>{need}</strong>.
    </div>
  )
}

export function SummaryCards(props: Props) {
  const { result, filters, state, presets } = props

  return (
    <div className="summary">
      <div className="summary-head">
        <div>
          <span className="big">{result.remainingGames.toLocaleString()}</span>
          <span className="big-label">games in scope</span>
        </div>
        <div className="parity">
          CLI default qualifies <strong>{props.defaultQualifying}</strong>
          {result.remainingGames === props.defaultQualifying && (
            <span className="ok"> ✓ match</span>
          )}
        </div>
      </div>

      <TargetBanner {...props} />

      <div className="cards">
        {CARDS.map((c) => {
          const active = filters.basis === c.basis
          const isPace = c.basis === 'pace'
          const total = basisTotal(result, c.basis)
          const headlineEta = isPace
            ? paceDays(result.remainingGames, state.pace_games_per_day)
            : etaDays(total as number, filters.dailyHours)

          return (
            <div key={c.basis} className={active ? 'card active' : 'card'}>
              <div className="card-title">{c.title}</div>
              <div className="card-blurb">{c.blurb}</div>
              <div className="card-total">
                {isPace
                  ? `${state.pace_games_per_day || 0} games/day`
                  : fmtHours(total as number)}
              </div>
              <div className="card-eta">
                {isPace && !state.pace_games_per_day
                  ? 'No start date set'
                  : fmtEta(headlineEta)}
              </div>
              {!isPace && (
                <div className="presets">
                  {presets.map((h) => (
                    <div key={h} className="preset">
                      <span>{h} h/day</span>
                      <span>{fmtEta(etaDays(total as number, h))}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
