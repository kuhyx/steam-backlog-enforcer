import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { apiError, flush, mount, stubApi } from '../../test/harness'
import { makePaceVsHltb } from '../../test/factories'
import './index'

const summary = { qualifying: 42, rush_total: 100, leisure_total: 250, worst_total: 400 }
const stats = (pace: ReturnType<typeof makePaceVsHltb> | null) => ({ default_summary: summary, pace_vs_hltb: pace })
async function show(reply: unknown) {
  stubApi({ 'GET /api/stats': reply as object })
  mount('<backlog-stats></backlog-stats>')
  await flush()
}
// A fact's label is spoken only (sr-only inside the dt's glyph).
const fact = (label: string) => screen.getByText(label, { selector: 'dt .sr-only' }).closest('dt')?.nextElementSibling

describe('<backlog-stats>', () => {
  it('shows the estimates for the default filters', async () => {
    await show(stats(null))
    expect(screen.getByRole('heading', { name: 'Estimates (default filters)' })).toBeInTheDocument()
    expect(screen.getByText('qualifying games')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('100 h')).toBeInTheDocument()
    expect(screen.getByText('250 h')).toBeInTheDocument()
    expect(screen.getByText('400 h')).toBeInTheDocument()
    expect(screen.queryByText('Your pace')).toBeNull()
  })

  it('adds the player’s pace against HLTB once calibrated', async () => {
    await show(stats(makePaceVsHltb({ player_style: 'rush_to_leisure', ratio_vs_rush: 1.05, ratio_vs_leisure: 0.4, calibration_count: 12 })))
    expect(fact('Your pace')).toHaveTextContent('Between rush and leisure')
    expect(fact('vs rush')).toHaveTextContent('1.05×')
    expect(fact('vs leisure')).toHaveTextContent('0.40×')
    expect(fact('Calibrated on')).toHaveTextContent('12 finished games')
  })

  it('dashes a ratio the server could not compute', async () => {
    await show(stats(makePaceVsHltb({ player_style: 'unknown', ratio_vs_rush: -1, ratio_vs_leisure: -1 })))
    expect(screen.getByText('Not enough finished games yet')).toHaveClass('sr-only')
    expect(fact('Your pace')?.querySelector('.player-insight-style--unknown')).not.toBeNull()
    expect(fact('vs rush')).toHaveTextContent('—')
    expect(fact('vs leisure')).toHaveTextContent('—')
  })

  it('shows an unlabelled style as its key', async () => {
    await show(stats(makePaceVsHltb({ player_style: 'odd' as 'unknown' })))
    expect(fact('Your pace')).toHaveTextContent('odd')
  })

  it('shows loading while stats load', async () => {
    await show(() => new Promise(() => undefined))
    expect(screen.getByText(/Loading stats/)).toBeInTheDocument()
  })

  it('explains a failed stats load', async () => {
    await show(apiError(500, 'op_failed', 'stats broke'))
    expect(screen.getByText('stats broke')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Estimates' })).toBeInTheDocument()
  })
})
