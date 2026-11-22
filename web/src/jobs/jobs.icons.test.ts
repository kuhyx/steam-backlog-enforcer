// Pass 2 wiring for the jobs page, the job view, the prompt form and the
// top-bar job chip: ledger words right of the icons, chosen glyphs applied,
// accessible names unchanged.

import { screen } from '@testing-library/dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PromptEvent } from './hub'
import { promptForm } from './promptForm'
import { jobChip } from '../shell/jobIndicator'
import '../sections/jobs'
import { makeJob, makeSpec } from '../test/fixtures'
import { installEventSource, mount, stubApi } from '../test/harness'
import { useIcons } from '../test/iconLedger'
import { mountJob } from '../test/jobHelpers'

beforeEach(installEventSource)

const word = (el: Element | null | undefined) => el?.nextElementSibling?.textContent
const prompt = (over: Partial<PromptEvent>): PromptEvent => ({
  seq: 1, ts: 't', type: 'prompt', prompt_id: 'q1', kind: 'confirm', message: 'Sure?', ...over,
})

describe('job view icons', () => {
  it('the title shows the command word and chosen glyph (cmd id), the name stays spoken', async () => {
    useIcons({ 'cmd.scan': { word: 'survey', glyph: '🛰️' } })
    const { el } = mountJob({ job: { state: 'running' } })
    await vi.waitFor(() => { expect(el.querySelector('h3 .sr-only')).toHaveTextContent('Scan') })
    const icon = el.querySelector('h3 [data-icon="cmd.scan"]')
    expect(icon?.textContent).toBe('🛰️')
    expect(word(icon)).toBe('Survey')
  })

  it('a failed end-of-window re-block shows as its own re-block job', async () => {
    const { el } = mountJob({ job: { command: 're-block', state: 'failed' } })
    await vi.waitFor(() => { expect(el.querySelector('h3 .sr-only')).toHaveTextContent('Re block') })
    expect(el.querySelector('h3 [data-icon="cmd.re-block"]')?.textContent).toBe('🔒')
  })

  it('the phase mark, the log count and the cancel button use their ids', async () => {
    useIcons({ 'job.state.running': { word: 'busy' }, 'jobs.log': { word: 'log' }, 'jobs.cancel': { word: 'stop' } })
    const { el, send } = mountJob({ job: { state: 'running' }, cancellable: true })
    send('progress', { step: 1, total: 3, label: 'Working' })
    await vi.waitFor(() => { expect(el.querySelector('.job-label [data-icon="job.state.running"]')).not.toBeNull() })
    expect(word(el.querySelector('.job-label [data-icon="job.state.running"]'))).toBe('Busy')
    expect(word(el.querySelector('summary [data-icon="jobs.log"]'))).toBe('Log')
    await vi.waitFor(() => { expect(screen.getByRole('button', { name: 'Cancel job' })).toBeInTheDocument() })
    expect(word(screen.getByRole('button', { name: 'Cancel job' }).querySelector('[data-icon="jobs.cancel"]'))).toBe('Stop')
  })
})

describe('jobs page icons', () => {
  it('the history headers paint their words, the column names stay spoken', async () => {
    history.replaceState({}, '', '/jobs/')
    useIcons({ 'jobs.took': { word: 'duration', glyph: '⌛' } })
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'a' })], 'GET /api/commands': [makeSpec('scan')] })
    mount('<jobs-page></jobs-page>')
    const took = (await screen.findByText('Took', { selector: 'th .sr-only' })).closest('th')
    expect(took?.querySelector('[data-icon="jobs.took"]')?.textContent).toBe('⌛')
    expect(word(took?.querySelector('[data-icon="jobs.took"]'))).toBe('Duration')
  })
})

describe('prompt form icons', () => {
  it('Yes and No buttons keep their aria-labels and paint their words', () => {
    useIcons({ 'prompt.yes': { word: 'agree' }, 'prompt.no': { word: 'refuse', glyph: '👎' } })
    const form = promptForm('j', prompt({}))
    document.body.append(form)
    const yes = screen.getByRole('button', { name: 'Yes' })
    expect(word(yes.querySelector('[data-icon="prompt.yes"]'))).toBe('Agree')
    const no = screen.getByRole('button', { name: 'No' })
    expect(no.querySelector('[data-icon="prompt.no"]')?.textContent).toBe('👎')
    expect(word(no.querySelector('[data-icon="prompt.no"]'))).toBe('Refuse')
  })

  it('the question mark and the answer button follow the ledger', () => {
    useIcons({ 'prompt.question': { word: 'ask' }, 'prompt.answer': { word: 'send', glyph: '📤' } })
    const form = promptForm('j', prompt({ kind: 'text' }))
    document.body.append(form)
    expect(word(form.querySelector('[data-icon="prompt.question"]'))).toBe('Ask')
    const answer = screen.getByRole('button', { name: 'Answer' })
    expect(answer.querySelector('[data-icon="prompt.answer"]')?.textContent).toBe('📤')
    expect(word(answer.querySelector('[data-icon="prompt.answer"]'))).toBe('Send')
  })
})

describe('job chip icon', () => {
  it('the needs-input mark paints its word, the aria-label keeps the sentence', () => {
    useIcons({ 'jobchip.needs-input': { word: 'answer', glyph: '🙋' } })
    const chip = jobChip(makeJob({ id: 'chip-wait', command: 'scan', state: 'waiting_input' }))
    const mark = chip.querySelector('[data-icon="jobchip.needs-input"]')
    expect(mark?.textContent).toBe('🙋')
    expect(word(mark)).toBe('Answer')
    expect(chip).toHaveAttribute('aria-label', 'Scan: needs your input')
  })
})
