// The gaming page paints every icon through the registry: the user's word
// shows right of the icon, a chosen alternative glyph replaces the default,
// and the spoken sentence stays as it was.

import { screen } from '@testing-library/dom'
import { afterEach, describe, expect, it } from 'vitest'
import { OTHER_KEY } from '../../budgetSeries'
import { makeBudgetRules, makeBudgetSession, makeBudgetToday } from '../../test/factories'
import { mount } from '../../test/harness'
import { useIcons } from '../../test/iconLedger'
import { liveCard, rulesCard, seriesLabel, todayCard, todayUnavailable } from './cards'
import './panel'

const show = (el: HTMLElement) => {
  document.body.replaceChildren(el)
}
const words = () => [...document.querySelectorAll('.icon-word')].map((w) => w.textContent)

afterEach(() => {
  history.replaceState(null, '', '/')
})

describe('gaming page icons', () => {
  it('rules card: a word right of the row icon, an alternative glyph, spoken names kept', () => {
    useIcons({ 'gaming.budget': { word: 'allowance' }, 'gaming.enforcement': { glyph: '⚔️' }, 'state.yes': { word: 'on' } })
    show(rulesCard(makeBudgetRules()))
    const term = document.querySelector('dt')
    expect(term?.querySelector('[data-icon]')?.nextElementSibling).toHaveClass('icon-word')
    expect(term?.querySelector('.icon-word')?.textContent).toBe('Allowance')
    expect(term?.querySelector('.sr-only')?.textContent).toBe('Daily budget')
    expect(document.querySelectorAll('dt').item(1).querySelector('[data-icon]')?.textContent).toBe('⚔️')
    expect(words()).toEqual(['Allowance', 'On', 'On'])
  })

  it('today card: warning, gaming day and heading icons carry the words', () => {
    useIcons({ 'gaming.warning': { word: 'bell' }, 'gaming.day': { word: 'date' }, 'gaming.today': { glyph: '🗓️' } })
    show(todayCard(makeBudgetToday(), [], 0))
    expect(words()).toEqual(['Date', 'Bell'])
    expect(screen.getByText(/Next warning at 1h 0m remaining/)).toBeInTheDocument()
    expect(document.querySelector('h2 [data-icon]')?.textContent).toBe('🗓️')
  })

  it('unavailable and empty marks reuse the shared state icons', () => {
    useIcons({ 'state.warn': { word: 'attention' } })
    show(todayUnavailable(null))
    expect(words()).toEqual(['Attention'])
    expect(screen.getByText('Budget state unavailable.')).toBeInTheDocument()
  })

  it('live card: the verdict icon swaps and the billing icon shows its word', () => {
    useIcons({ 'dash.billing': { glyph: '⏺️' }, 'gaming.billing_to': { word: 'charging' }, 'assigned.game': { word: 'target' } })
    show(liveCard(makeBudgetSession()))
    expect(document.querySelector('.budget-verdict [data-icon]')?.textContent).toBe('⏺️')
    expect(words()).toEqual(['Target', 'Charging'])
    expect(screen.getByText('Billing to')).toBeInTheDocument()
    expect(screen.getByText('Billing — you are playing')).toBeInTheDocument()
  })

  it('series labels: the other-games sentinel and a launcher carry their icons', () => {
    useIcons({ 'gaming.series.other': { word: 'rest' }, 'gaming.launcher': { word: 'client' } })
    show(wrap(seriesLabel(OTHER_KEY, 'Other games')))
    expect(words()).toEqual(['Rest'])
    show(wrap(seriesLabel('launcher:epic', 'Epic (launcher)')))
    expect(words()).toEqual(['Client'])
    expect(document.body.textContent).toContain('Epic')
  })

  it('mode link: the demo and production icons take the chosen glyph', () => {
    useIcons({ 'gaming.demo': { glyph: '🔬' }, 'gaming.production': { glyph: '🏢' } })
    mount('<budget-mode-link></budget-mode-link>')
    expect(screen.getByRole('link', { name: 'Show demo budget' }).querySelector('[data-icon]')?.textContent).toBe('🔬')
    history.replaceState(null, '', '/gaming/?demo=1')
    mount('<budget-mode-link></budget-mode-link>')
    expect(screen.getByRole('link', { name: 'Show production budget' }).querySelector('[data-icon]')?.textContent).toBe('🏢')
  })
})

function wrap(child: HTMLElement): HTMLElement {
  const el = document.createElement('div')
  el.append(child)
  return el
}
