// <backlog-stats>: the CLI's `stats` estimate for the default filters (was
// screens/Backlog.tsx StatsCard). Textgate: labels are icons, words spoken only.

import { q } from '../../api/queries'
import { fmtHours } from '../../format'
import type { IconId } from '../../icons/registry'
import { h } from '../../lib/dom'
import { LiveElement } from '../../lib/element'
import { card, errorNotice, facts, glyph, loading } from '../../ui/build'
import { BASIS_ICON, styleGlyph } from './glyphs'

const ICON: IconId = 'stats.card'
const ratio = (r: number) => (r < 0 ? '—' : `${r.toFixed(2)}×`)
const stat = (num: string | number, icon: IconId, label: string) =>
  h('div', { class: 'stat' }, h('span', { class: 'stat-num' }, num), glyph(icon, label, 'stat-label'))

export class BacklogStatsElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.stats)
  }

  protected update(): void {
    const { data, error } = q.stats.state
    if (error) {
      this.replaceChildren(card('Estimates', errorNotice(error), { icon: ICON }))
      return
    }
    if (!data) {
      this.replaceChildren(card('Estimates', loading('stats'), { icon: ICON }))
      return
    }
    const s = data.default_summary
    const p = data.pace_vs_hltb
    this.replaceChildren(
      card(
        'Estimates (default filters)',
        [
          h(
            'div',
            { class: 'stat-row' },
            stat(s.qualifying, 'backlog.in-scope', 'qualifying games'),
            stat(fmtHours(s.rush_total), BASIS_ICON.rush, 'rush'),
            stat(fmtHours(s.leisure_total), BASIS_ICON.leisure, 'leisure'),
            stat(fmtHours(s.worst_total), BASIS_ICON.worst, 'worst case'),
          ),
          p
            ? facts([
                [glyph(BASIS_ICON.pace, 'Your pace'), styleGlyph(p.player_style)],
                [glyph(BASIS_ICON.rush, 'vs rush'), ratio(p.ratio_vs_rush)],
                [glyph(BASIS_ICON.leisure, 'vs leisure'), ratio(p.ratio_vs_leisure)],
                [glyph('dash.finished','Calibrated on'), [String(p.calibration_count), h('span', { class: 'sr-only' }, ' finished games')]],
              ])
            : null,
        ],
        { icon: ICON },
      ),
    )
  }
}
