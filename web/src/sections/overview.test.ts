import { screen, waitFor } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeDataset, makeGame } from '../test/factories'
import { apiError, mount, stubApi } from '../test/harness'
import './overview'

const games = [
  makeGame({ app_id: 1, name: 'Alpha' }),
  makeGame({ app_id: 2, name: 'Beta' }),
  makeGame({ app_id: 3, name: 'Gamma' }),
]

describe('backlog-overview (dashboard)', () => {
  it('shows the default-filter summary cards and the completion timeline chart', async () => {
    stubApi({ 'GET /api/dataset': makeDataset(games) })
    const el = mount('<backlog-overview></backlog-overview>')
    expect(screen.getByText('Backlog outlook')).toBeInTheDocument()
    await waitFor(() => {
      expect(el.querySelector('.summary .cards')).not.toBeNull()
    })
    expect(el.querySelectorAll('.summary .cards > *')).toHaveLength(4)
    expect(el.querySelector('.planner-wrap .summary')).not.toBeNull()
    expect(el.querySelector('.chart svg')).not.toBeNull()
    expect(screen.getByRole('link', { name: 'Open the planner' })).toHaveAttribute('href', '/backlog/')
  })

  it('says why there is no chart when too few games qualify', async () => {
    stubApi({ 'GET /api/dataset': makeDataset([]) })
    const el = mount('<backlog-overview></backlog-overview>')
    expect(await screen.findByText('Not enough games in scope to draw a timeline.')).toBeInTheDocument()
    expect(el.querySelector('.chart svg')).toBeNull()
  })

  it('shows loading until the dataset arrives', () => {
    stubApi({ 'GET /api/dataset': () => new Promise(() => undefined) })
    mount('<backlog-overview></backlog-overview>')
    expect(screen.getByRole('status')).toHaveTextContent('Loading backlog')
  })

  it('explains a failed dataset read', async () => {
    stubApi({ 'GET /api/dataset': apiError(500, 'op_failed', 'dataset broke') })
    mount('<backlog-overview></backlog-overview>')
    // /api/dataset goes through api.ts getJson, which reports the HTTP status.
    expect(await screen.findByText('API returned 500 Error')).toBeInTheDocument()
  })
})
