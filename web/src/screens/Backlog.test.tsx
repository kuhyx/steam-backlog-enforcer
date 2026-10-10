import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeDataset, makeGame, makePaceVsHltb } from '../test/factories'
import { apiError, renderClient, stubApi } from '../test/harness'
import { Backlog } from './Backlog'

const summary = { qualifying: 42, rush_total: 100, leisure_total: 250, worst_total: 400 }
const stats = (pace: ReturnType<typeof makePaceVsHltb> | null) => ({ default_summary: summary, pace_vs_hltb: pace })
const show = (statsReply: unknown) => {
  stubApi({ 'GET /api/stats': statsReply, 'GET /api/dataset': makeDataset([makeGame({ app_id: 1, name: 'Alpha' }), makeGame({ app_id: 2, name: 'Beta' })]) })
  renderClient(<Backlog />)
}
const fact = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling!

describe('Backlog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the estimates for the default filters', async () => {
    show(stats(null))
    expect(await screen.findByText('qualifying games')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('100 h')).toBeInTheDocument()
    expect(screen.getByText('250 h')).toBeInTheDocument()
    expect(screen.getByText('400 h')).toBeInTheDocument()
    expect(screen.queryByText('Your pace')).toBeNull()
  })

  it('adds the player’s pace against HLTB once calibrated', async () => {
    show(stats(makePaceVsHltb({ player_style: 'rush_to_leisure', ratio_vs_rush: 1.05, ratio_vs_leisure: 0.4, calibration_count: 12 })))
    expect(await screen.findByText('Your pace')).toBeInTheDocument()
    expect(fact('Your pace')).toHaveTextContent('Between rush and leisure')
    expect(fact('vs rush')).toHaveTextContent('1.05×')
    expect(fact('vs leisure')).toHaveTextContent('0.40×')
    expect(fact('Calibrated on')).toHaveTextContent('12 finished games')
  })

  it('dashes a ratio the server could not compute', async () => {
    show(stats(makePaceVsHltb({ player_style: 'unknown', ratio_vs_rush: -1, ratio_vs_leisure: -1 })))
    expect(await screen.findByText('Not enough finished games yet')).toBeInTheDocument()
    expect(fact('vs rush')).toHaveTextContent('—')
    expect(fact('vs leisure')).toHaveTextContent('—')
  })

  it('shows loading while stats load', async () => {
    show(() => new Promise(() => {}))
    expect(await screen.findByText(/Loading stats/)).toBeInTheDocument()
  })

  it('explains a failed stats load', async () => {
    show(apiError(500, 'op_failed', 'stats broke'))
    expect(await screen.findByText('stats broke')).toBeInTheDocument()
  })

  it('embeds the interactive planner', async () => {
    show(stats(null))
    expect(await screen.findByRole('heading', { name: 'Backlog Completion Planner' })).toBeInTheDocument()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('Alpha')).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText(/Search games/i), 'Beta')
    expect(within(table).queryByText('Alpha')).toBeNull()
  })
})
