// <backlog-stats>: the CLI's `stats` estimate for the default filters (was
// screens/Backlog.tsx StatsCard).

import { q } from '../../api/queries'
import { fmtHours } from '../../format'
import { h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { card, errorNotice, facts, loading } from '../../ui/build'

const STYLE: Record<string, string> = {
  faster_than_rush: 'Faster than HLTB rush',
  rush_to_leisure: 'Between rush and leisure',
  slower_than_leisure: 'Slower than HLTB leisure',
  unknown: 'Not enough finished games yet',
}

const ratio = (r: number) => (r < 0 ? '—' : `${r.toFixed(2)}×`)
const stat = (num: string | number, label: string) =>
  h('div', { class: 'stat' }, h('span', { class: 'stat-num' }, num), h('span', { class: 'stat-label' }, label))

export class BacklogStatsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.stats)
  }

  protected update(): void {
    const { data, error } = q.stats.state
    if (error) {
      this.replaceChildren(card('Estimates', errorNotice(error)))
      return
    }
    if (!data) {
      this.replaceChildren(card('Estimates', loading('stats')))
      return
    }
    const s = data.default_summary
    const p = data.pace_vs_hltb
    this.replaceChildren(
      card('Estimates (default filters)', [
        h(
          'div',
          { class: 'stat-row' },
          stat(s.qualifying, 'qualifying games'),
          stat(fmtHours(s.rush_total), 'rush'),
          stat(fmtHours(s.leisure_total), 'leisure'),
          stat(fmtHours(s.worst_total), 'worst case'),
        ),
        p
          ? facts([
              ['Your pace', STYLE[p.player_style] ?? p.player_style],
              ['vs rush', ratio(p.ratio_vs_rush)],
              ['vs leisure', ratio(p.ratio_vs_leisure)],
              ['Calibrated on', `${p.calibration_count} finished games`],
            ])
          : null,
      ]),
    )
  }
}
