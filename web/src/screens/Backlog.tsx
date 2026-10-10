import { useQuery } from '@tanstack/react-query'
import { q } from '../api/queries'
import { PlannerView } from '../components/PlannerView'
import { fmtHours } from '../format'
import { ErrorNotice, Loading } from '../ui/Notice'
import { Card, Facts, PageHead } from '../ui/Page'

const STYLE: Record<string, string> = {
  faster_than_rush: 'Faster than HLTB rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than HLTB leisure',
  unknown: 'Not enough finished games yet',
}

/** `stats`: the CLI's completion-time estimate for the default filters. */
function StatsCard() {
  const { data, error } = useQuery(q.stats)
  if (error) return <Card title="Estimates"><ErrorNotice error={error} /></Card>
  if (!data) return <Card title="Estimates"><Loading what="stats" /></Card>
  const s = data.default_summary
  const p = data.pace_vs_hltb
  return (
    <Card title="Estimates (default filters)">
      <div className="stat-row">
        <div className="stat"><span className="stat-num">{s.qualifying}</span><span className="stat-label">qualifying games</span></div>
        <div className="stat"><span className="stat-num">{fmtHours(s.rush_total)}</span><span className="stat-label">rush</span></div>
        <div className="stat"><span className="stat-num">{fmtHours(s.leisure_total)}</span><span className="stat-label">leisure</span></div>
        <div className="stat"><span className="stat-num">{fmtHours(s.worst_total)}</span><span className="stat-label">worst case</span></div>
      </div>
      {p && (
        <Facts
          rows={[
            ['Your pace', STYLE[p.player_style]],
            ['vs rush', p.ratio_vs_rush < 0 ? '—' : `${p.ratio_vs_rush.toFixed(2)}×`],
            ['vs leisure', p.ratio_vs_leisure < 0 ? '—' : `${p.ratio_vs_leisure.toFixed(2)}×`],
            ['Calibrated on', `${p.calibration_count} finished games`],
          ]}
        />
      )}
    </Card>
  )
}

export function Backlog() {
  return (
    <>
      <PageHead title="Backlog" sub="Completion estimates (stats) and every candidate game (list), with the interactive planner." />
      <StatsCard />
      <div className="planner-wrap">
        <PlannerView />
      </div>
    </>
  )
}
