import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeStatus } from '../test/fixtures'
import { apiError, mount, stubApi } from '../test/harness'
import './picks'

const pick = (app_id: number, name: string) => ({ app_id, name, age_days: 3 })

describe('picks-sub', () => {
  it('names the assigned game', async () => {
    stubApi({ 'GET /api/status': makeStatus({ current_game_name: 'Hades' }) })
    mount('<picks-sub></picks-sub>')
    expect(await screen.findByText('Hades')).toBeInTheDocument()
    expect(document.body).toHaveTextContent('Assigned: Hades')
  })

  it('explains the page while nothing is assigned', () => {
    stubApi({ 'GET /api/status': () => new Promise(() => undefined) })
    mount('<picks-sub></picks-sub>')
    expect(document.body).toHaveTextContent('Which game you are playing, and how to move on.')
  })
})

describe('manual-picks', () => {
  it('lists manual and kept picks, each with an abandon button', async () => {
    stubApi({
      'GET /api/status': makeStatus({ manual_picks: [pick(1, 'Celeste')], kept_picks: [pick(2, 'Hades')] }),
      'GET /api/commands': [],
    })
    mount('<manual-picks></manual-picks>')
    expect(await screen.findByText('Celeste')).toBeInTheDocument()
    expect(screen.getByText('· picked 3 d ago · 1')).toBeInTheDocument()
    expect(screen.getByText('· kept · no lock · 2')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Abandon…' })).toHaveLength(2)
    expect(screen.queryByText(/No manual picks/)).toBeNull()
  })

  it('offers abandon-by-id when there are no picks', async () => {
    stubApi({ 'GET /api/status': makeStatus(), 'GET /api/commands': [] })
    mount('<manual-picks></manual-picks>')
    expect(await screen.findByText(/No manual picks/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Abandon a pick by app id…' })).toBeInTheDocument()
  })

  it('shows loading, then the error', async () => {
    let fail = false
    stubApi({
      'GET /api/status': () => (fail ? apiError(500, 'op_failed', 'boom') : new Promise(() => undefined)),
    })
    mount('<manual-picks></manual-picks>')
    expect(screen.getByRole('status')).toHaveTextContent('Loading status')
    document.body.replaceChildren()
    fail = true
    const { q } = await import('../api/queries')
    q.status.reset()
    mount('<manual-picks></manual-picks>')
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })
})
