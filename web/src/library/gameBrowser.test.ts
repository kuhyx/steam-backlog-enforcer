import { fireEvent, screen } from '@testing-library/dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { q } from '../api/queries'
import { apiError, stubApi } from '../test/harness'
import { GAMES, render, search, titles, withLibrary } from '../test/browserHelpers'

describe('GameBrowser', () => {
  beforeEach(() => {
    withLibrary()
  })

  it('shows the library sorted by name, with a count', async () => {
    render()
    expect(screen.getByText(/Loading your library/)).toBeInTheDocument()
    await screen.findByText('5 of 5 games')
    expect(titles()).toEqual(['Age of Empires III', 'Hollow Knight', 'The Witcher', 'The Witcher 2', 'The Witcher 3'])
    expect(screen.queryByText(/Loading/)).toBeNull()
    expect(document.querySelector('game-browser')).toHaveClass('lib')
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/library': apiError(500, 'op_failed', 'cannot read library') })
    render()
    expect(await screen.findByText('cannot read library')).toBeInTheDocument()
    expect(screen.queryByText(/Loading/)).toBeNull()
  })

  it('keeps the grid and shows the error when a refetch fails', async () => {
    const routes: Record<string, unknown> = { 'GET /api/library': { games: GAMES } }
    stubApi(routes as never)
    render()
    await screen.findByText('5 of 5 games')
    routes['GET /api/library'] = apiError(500, 'op_failed', 'refetch broke')
    q.library.invalidate()
    expect(await screen.findByText('refetch broke')).toBeInTheDocument()
    expect(titles()).toHaveLength(5)
  })

  it('says so when nothing matches', async () => {
    withLibrary([])
    render()
    expect(await screen.findByText('No game matches.')).toBeInTheDocument()
    expect(screen.getByText('0 of 0 games')).toBeInTheDocument()
  })

  it('drops a pending grid frame when detached', async () => {
    const el = render()
    await screen.findByText('5 of 5 games')
    fireEvent.input(search(), { target: { value: 'hollow' } })
    el.remove()
    await new Promise((r) => setTimeout(r, 40))
    expect(el.querySelectorAll('.game-card')).toHaveLength(5)
  })
})
