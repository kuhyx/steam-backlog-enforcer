import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, bodiesOf, renderClient, stubApi } from '../test/harness'
import { hub, type PromptEvent } from './hub'
import { PromptForm } from './PromptForm'

const prompt = (over: Partial<PromptEvent> = {}): PromptEvent => ({
  seq: 1, ts: 't', type: 'prompt', prompt_id: 'q1', kind: 'text', message: 'Which one?', ...over,
})

describe('PromptForm', () => {
  afterEach(() => vi.unstubAllGlobals())

  describe('choice', () => {
    const options = [
      { value: 'a', label: 'Alpha', detail: 'the first' },
      { value: 'b', label: 'Beta' },
    ]

    it('is a radio group, first option focused, nothing preselected', () => {
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'choice', options })} />)
      expect(screen.getByRole('radio', { name: /Alpha/ })).toHaveFocus()
      expect(screen.getByText('the first')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Answer' })).toBeDisabled()
    })

    it('sends the chosen value and hides the prompt', async () => {
      const mock = stubApi({ 'POST /api/jobs/j/answer': undefined })
      const answered = vi.spyOn(hub, 'answered')
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'choice', options })} />)
      await userEvent.click(screen.getByRole('radio', { name: /Beta/ }))
      expect(screen.getByText('Beta').closest('label')).toHaveClass('selected')
      await userEvent.click(screen.getByRole('button', { name: 'Answer' }))
      await waitFor(() => expect(answered).toHaveBeenCalledWith('j', 'q1'))
      expect(bodiesOf(mock, 'POST /api/jobs/j/answer')).toEqual([{ prompt_id: 'q1', value: 'b' }])
    })

    it('honours a default and tolerates missing options', () => {
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'choice', default: 'a' })} />)
      expect(screen.getByRole('button', { name: 'Answer' })).toBeEnabled()
      expect(screen.queryAllByRole('radio')).toHaveLength(0)
    })
  })

  describe('text', () => {
    it('submits on Enter, even empty', async () => {
      const mock = stubApi({ 'POST /api/jobs/j/answer': undefined })
      renderClient(<PromptForm jobId="j" prompt={prompt({ default: 'x' })} />)
      expect(screen.getByRole('textbox', { name: 'Which one?' })).toHaveFocus()
      await userEvent.type(screen.getByRole('textbox'), 'y{Enter}')
      await waitFor(() => expect(bodiesOf(mock, 'POST /api/jobs/j/answer')).toEqual([{ prompt_id: 'q1', value: 'xy' }]))
    })
  })

  describe('confirm', () => {
    it('answers yes or no, yes focused by default', async () => {
      const mock = stubApi({ 'POST /api/jobs/j/answer': undefined })
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'confirm' })} />)
      expect(screen.getByRole('button', { name: 'Yes' })).toHaveFocus()
      await userEvent.click(screen.getByRole('button', { name: 'Yes' }))
      await userEvent.click(screen.getByRole('button', { name: 'No' }))
      await waitFor(() =>
        expect(bodiesOf(mock, 'POST /api/jobs/j/answer').map((b) => (b as { value: string }).value)).toEqual(['yes', 'no']),
      )
    })

    it('focuses No when that is the default', () => {
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'confirm', default: 'no' })} />)
      expect(screen.getByRole('button', { name: 'No' })).toHaveFocus()
    })
  })

  describe('phrase', () => {
    it('stays disabled until the phrase is typed exactly', async () => {
      const mock = stubApi({ 'POST /api/jobs/j/answer': undefined })
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'phrase', phrase: 'do it' })} />)
      const answer = screen.getByRole('button', { name: 'Answer' })
      await userEvent.type(screen.getByRole('textbox'), 'do i')
      expect(answer).toBeDisabled()
      await userEvent.type(screen.getByRole('textbox'), 't')
      expect(answer).toBeEnabled()
      await userEvent.click(answer)
      await waitFor(() => expect(bodiesOf(mock, 'POST /api/jobs/j/answer')).toEqual([{ prompt_id: 'q1', value: 'do it' }]))
    })

    it('copes with a prompt that lost its phrase', () => {
      renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'phrase' })} />)
      expect(screen.getByRole('button', { name: 'Answer' })).toBeEnabled() // '' matches ''
    })
  })

  it('shows the server error when the answer is refused', async () => {
    stubApi({ 'POST /api/jobs/j/answer': apiError(404, 'not_found', 'job is gone') })
    renderClient(<PromptForm jobId="j" prompt={prompt()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Answer' }))
    expect(await screen.findByText('job is gone')).toBeInTheDocument()
  })

  it('disables the buttons while sending', async () => {
    let release: () => void = () => {}
    stubApi({ 'POST /api/jobs/j/answer': () => new Promise<void>((r) => (release = r)) })
    renderClient(<PromptForm jobId="j" prompt={prompt({ kind: 'confirm' })} />)
    await userEvent.click(screen.getByRole('button', { name: 'Yes' }))
    expect(screen.getByRole('button', { name: 'Yes' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'No' })).toBeDisabled()
    await act(async () => release())
  })

  it('shows Sending… on the answer button', async () => {
    let release: () => void = () => {}
    stubApi({ 'POST /api/jobs/j/answer': () => new Promise<void>((r) => (release = r)) })
    renderClient(<PromptForm jobId="j" prompt={prompt()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Answer' }))
    expect(await screen.findByRole('button', { name: 'Sending…' })).toBeDisabled()
    await act(async () => release())
  })
})
