import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { makeLibGame } from '../test/fixtures'
import { apiError, bodiesOf, renderClient, stubApi } from '../test/harness'
import { GamePrompt } from './GamePrompt'
import { hub, type PromptEvent } from './hub'
import { PromptForm } from './PromptForm'

const GAMES = [
  makeLibGame({ app_id: 1, name: 'Hollow Knight' }),
  makeLibGame({ app_id: 2, name: 'The Witcher 2' }),
  makeLibGame({ app_id: 3, name: 'Age of Empires III', ineligible_reason: 'Not owned for long enough' }),
]
const prompt = (over: Partial<PromptEvent> = {}): PromptEvent => ({
  seq: 1, ts: 't', type: 'prompt', prompt_id: 'g1', kind: 'game', message: 'Pick a game', app_ids: [1, 2], ...over,
})
const ANSWER = 'POST /api/jobs/j/answer'
const card = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) })

describe('GamePrompt', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is rendered by PromptForm for a game prompt', async () => {
    stubApi({ 'GET /api/library': { games: GAMES } })
    renderClient(<PromptForm jobId="j" prompt={prompt()} />)
    expect(await screen.findByRole('form', { name: 'Job question' })).toHaveTextContent('2 games can be picked')
  })

  it('selecting a card never submits; only the Pick button does', async () => {
    const mock = stubApi({ 'GET /api/library': { games: GAMES }, [ANSWER]: undefined })
    const answered = vi.spyOn(hub, 'answered')
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    expect(screen.getByRole('button', { name: 'Select a game' })).toBeDisabled()
    await userEvent.click(card('The Witcher 2'))
    await userEvent.dblClick(card('The Witcher 2'))
    expect(bodiesOf(mock, ANSWER)).toEqual([])
    await userEvent.click(screen.getByRole('button', { name: 'Pick The Witcher 2' }))
    await waitFor(() => expect(bodiesOf(mock, ANSWER)).toEqual([{ prompt_id: 'g1', value: '2' }]))
    await waitFor(() => expect(answered).toHaveBeenCalledWith('j', 'g1'))
  })

  it('only offers the app ids the job sent', async () => {
    const mock = stubApi({ 'GET /api/library': { games: GAMES }, [ANSWER]: undefined })
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    await userEvent.click(card('Age of Empires III'))
    expect(screen.getByRole('button', { name: 'Select a game' })).toBeDisabled()
    expect(card('Age of Empires III')).toHaveTextContent('Not owned for long enough')
    expect(card('Hollow Knight')).not.toHaveAttribute('aria-disabled')
    expect(bodiesOf(mock, ANSWER)).toEqual([])
  })

  it('"Back to the list" answers an empty string', async () => {
    const mock = stubApi({ 'GET /api/library': { games: GAMES }, [ANSWER]: undefined })
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    await userEvent.click(screen.getByRole('button', { name: 'Back to the list' }))
    await waitFor(() => expect(bodiesOf(mock, ANSWER)).toEqual([{ prompt_id: 'g1', value: '' }]))
  })

  it('Enter in the form submits the selection, and does nothing without one', async () => {
    const mock = stubApi({ 'GET /api/library': { games: GAMES }, [ANSWER]: undefined })
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    const form = screen.getByRole('form', { name: 'Job question' })
    fireEvent.submit(form)
    expect(bodiesOf(mock, ANSWER)).toEqual([])
    await userEvent.click(card('Hollow Knight'))
    fireEvent.submit(form)
    await waitFor(() => expect(bodiesOf(mock, ANSWER)).toEqual([{ prompt_id: 'g1', value: '1' }]))
  })

  it('names the game by id if it vanished from the library meanwhile', async () => {
    const routes = { 'GET /api/library': { games: GAMES }, [ANSWER]: undefined }
    stubApi(routes)
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    await userEvent.click(card('Hollow Knight'))
    routes['GET /api/library'] = { games: [GAMES[1]] }
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['library'] })
    })
    expect(await screen.findByRole('button', { name: 'Pick 1' })).toBeInTheDocument()
  })

  it('copes with a prompt that carries no app ids', async () => {
    stubApi({ 'GET /api/library': { games: GAMES } })
    renderClient(<GamePrompt jobId="j" prompt={prompt({ app_ids: undefined })} />)
    expect(await screen.findByText(/0 games can be picked/)).toBeInTheDocument()
  })

  it('shows the error when the answer is refused, and Sending… meanwhile', async () => {
    let fail = false
    let release: () => void = () => {}
    stubApi({
      'GET /api/library': { games: GAMES },
      [ANSWER]: () => (fail ? apiError(409, 'busy', 'job moved on') : new Promise<void>((r) => (release = r))),
    })
    renderClient(<GamePrompt jobId="j" prompt={prompt()} />)
    await screen.findByText('3 of 3 games')
    await userEvent.click(card('Hollow Knight'))
    await userEvent.click(screen.getByRole('button', { name: 'Pick Hollow Knight' }))
    expect(await screen.findByRole('button', { name: 'Sending…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Back to the list' })).toBeDisabled()
    fail = true
    await act(async () => release())
    await userEvent.click(screen.getByRole('button', { name: 'Back to the list' }))
    expect(await screen.findByText('job moved on')).toBeInTheDocument()
  })
})
