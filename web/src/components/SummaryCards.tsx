import { basisTotal, etaDays, paceDays, playerEstimatedTotal } from '../estimate'
import type { EstimateResult } from '../estimate'
import { fmtEta, fmtHours } from '../format'
import type { EstimateBasis, Filters, PaceVsHLTB, WebStateInfo } from '../types'

interface Props {
  result: EstimateResult
  filters: Filters
  state: WebStateInfo
  presets: number[]
  defaultQualifying: number
  paceVsHltb: PaceVsHLTB | null
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

const STYLE_LABELS: Record<string, string> = {
  faster_than_rush: 'Faster than rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than leisure',
  unknown: 'Unknown',
}

function TargetBanner({ result, filters }: Props) {
  if (!filters.targetDate) return null
  const now = new Date()
  const target = new Date(filters.targetDate)
  const days = Math.max(1, Math.ceil((target.getTime() - now.getTime()) / 86400000))
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

function PlayerSpeedInsight({
  result,
  paceVsHltb,
  presets,
}: Pick<Props, 'result' | 'paceVsHltb' | 'presets'>) {
  const pace = paceVsHltb
  const estimated = playerEstimatedTotal(result.rushTotal, result.leisureTotal, pace)

  if (!pace || pace.calibration_count === 0) {
    return (
      <div className="player-insight player-insight--empty">
        <div className="player-insight-title">Your Play Style vs HLTB</div>
        <p className="player-insight-empty">
          No calibration data yet. Finish games (100% achievements) and re-run{' '}
          <code>stats</code> to see your pace estimate.
        </p>
      </div>
    )
  }

  return (
    <div className="player-insight">
      <div className="player-insight-title">Your Play Style vs HLTB</div>
      <div className="player-insight-grid">
        <span>Calibration games</span>
        <span>{pace.calibration_count}</span>

        {pace.ratio_vs_rush !== -1 && (
          <>
            <span>vs Rush speed</span>
            <span
              className={pace.ratio_vs_rush <= 1 ? 'player-insight-fast' : 'player-insight-slow'}
            >
              {pace.ratio_vs_rush.toFixed(2)}×
            </span>
          </>
        )}

        {pace.ratio_vs_leisure !== -1 && (
          <>
            <span>vs Leisure speed</span>
            <span>{pace.ratio_vs_leisure.toFixed(2)}×</span>
          </>
        )}

        {pace.interpolation_t !== -1 && (
          <>
            <span>Interpolation t</span>
            <span title="0 = rush speed · 1 = leisure speed">
              {pace.interpolation_t.toFixed(3)}
            </span>
          </>
        )}

        <span>Play style</span>
        <span className={`player-insight-style player-insight-style--${pace.player_style}`}>
          {STYLE_LABELS[pace.player_style] ?? pace.player_style}
        </span>
      </div>

      {estimated !== null && (
        <div className="player-insight-estimate">
          <div className="player-insight-estimate-total">
            Estimated total at your pace:{' '}
            <strong className="player-insight-estimate-hours">{fmtHours(estimated)}</strong>
          </div>
          <div className="presets">
            {presets.map((h) => {
              const days = estimated > 0 ? Math.floor(estimated / h) : null
              return (
                <div key={h} className="preset">
                  <span>{h} h/day</span>
                  <span>{fmtEta(days)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function SummaryCards(props: Props) {
  const { result, filters, state, presets, paceVsHltb } = props

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

      <PlayerSpeedInsight result={result} paceVsHltb={paceVsHltb} presets={presets} />
    </div>
  )
}
